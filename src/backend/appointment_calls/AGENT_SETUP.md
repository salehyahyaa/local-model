# ElevenLabs agent setup

Done once in your ElevenLabs account. Then add these to `.env` and restart the app:

```
ELEVENLABS_AGENT_ID=agent_...
ELEVENLABS_PHONE_NUMBER_ID=phnum_...
CALL_OWNER_NAME=Your Name
```

`ELEVENLABS_API_KEY` comes from `.env` or the keychain. After that, just ask the model in chat to make a call.

1. Import your Twilio number into ElevenLabs and copy its phone number ID.
2. Create a **Blank agent** and set its LLM to one of the two the app accepts:
   - **DeepSeek Flash 4.1** (`deepseek-v41-flash`), hosted by ElevenLabs. Set **Backup LLM** to **Disabled**, or the app refuses the agent, because the default backup hands calls to other hosted models.
   - **Custom LLM**, pointing at your own model's server. It must offer a streaming, OpenAI-compatible `/v1/chat/completions` with function calling, be reachable by ElevenLabs, and require authentication. Backup LLM may be Default or Disabled, but not a custom list.
3. In **Analysis**, the default analysis model reads every transcript to fill in the fields below. Set it to the model you want to see your transcripts.
4. Enable the `end_call` and `voicemail_detection` system tools. Don't leave a voicemail message.
5. Add these data collection fields:
   - `booked` (boolean): whether a reservation or appointment was agreed
   - `appointment_time` (string): the agreed start time in ISO 8601 with a UTC offset
   - `alternatives` (string): times offered that weren't accepted
   - `notes` (string): anything the owner needs to know, such as what to bring
   - `order_total` (string): the total quoted for a pickup order
6. Set the first message and system prompt below.

## Results by webhook

Results reach the app by ElevenLabs' post-call webhook. Checking ElevenLabs directly is only a backup, for calls whose webhook is more than 5 minutes late. The webhook runs as its own small server on port 8765, so the tunnel exposes only it and never the main app.

1. Start the webhook server first (step 4), check it's the one on port 8765, and only then start a tunnel to `http://127.0.0.1:8765`. A tunnel to a port with something else on it makes that app public.
2. In ElevenAgents → **Settings** → **Post-call webhook**, add `https://<tunnel address>/api/calls/webhook` and turn on the **transcript** and **call initiation failure** events. Leave audio off.
3. Copy the secret ElevenLabs shows, then run `venv/bin/python -m scripts.setup_call_webhook` and paste it. It's stored in the keychain.
4. Restart the app, then run `venv/bin/python -m src.backend.appointment_calls.webhook_server`.

Results arrive while the Mac is awake. Calls that end while it's asleep are picked up by the backup check when it wakes.

## First message

Hi, this is an AI assistant calling on behalf of {{booking_name}}. I'd like to make a booking. Is now a good time?

## System prompt

You are an AI assistant phoning {{contact_name}} to make a booking under the name {{booking_name}}. Say you're an AI if asked.

What the booking is for: {{reason}}

Times {{booking_name}} can do ({{timezone}}): {{allowed_slots}}

The booking must be before {{deadline}}.

Rules:
- Only agree to a time inside the times listed above.
- If none of them work, note the alternatives offered and accept none of them. Say {{booking_name}} will get back to them, thank them, say goodbye, and use `end_call`.
- Share only the name {{booking_name}} and the details above.
- Don't make payments, share other personal details, or agree to anything except this booking.
- Before ending the call, repeat the agreed date and time back to confirm it.
- If you reach voicemail or an automated system, end the call without leaving a message.
