-- Spending limits are set on the card in the bank's app, not here.

ALTER TABLE agentic_credit_cards DROP COLUMN per_purchase_limit, DROP COLUMN monthly_limit;
