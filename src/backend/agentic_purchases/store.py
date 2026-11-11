from src.backend import db
from src.backend.agentic_purchases.robinhood import PROVIDER


async def save_purchases(transactions, provider=PROVIDER):
    """Adds new purchases and updates ones whose status changed, like a pending charge that posted."""
    if not transactions:
        return
    pool = db.require_pool()
    await pool.executemany(
        """INSERT INTO agentic_purchases
               (user_id, provider, purchase_id, merchant, total, status, decline_reason, approval_status, purchased_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT (user_id, provider, purchase_id) DO UPDATE
           SET merchant = EXCLUDED.merchant, total = EXCLUDED.total, status = EXCLUDED.status,
               decline_reason = EXCLUDED.decline_reason, approval_status = EXCLUDED.approval_status,
               purchased_at = EXCLUDED.purchased_at, updated_at = now()""",
        [
            (
                db.user_id,
                provider,
                row["purchase_id"],
                row["merchant"],
                row["total"],
                row["status"],
                row["decline_reason"],
                row["approval_status"],
                row["purchased_at"],
            )
            for row in transactions
        ],
    )


async def list_purchases():
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT id, provider, merchant, total, status, decline_reason, approval_status, purchased_at
           FROM agentic_purchases WHERE user_id = $1 ORDER BY purchased_at DESC, id DESC""",
        db.user_id,
    )
    return [
        {
            "id": row["id"],
            "provider": row["provider"],
            "merchant": row["merchant"],
            "total": str(row["total"]),
            "status": row["status"],
            "declineReason": row["decline_reason"],
            "approvalStatus": row["approval_status"],
            "purchasedAt": row["purchased_at"].isoformat(),
        }
        for row in rows
    ]
