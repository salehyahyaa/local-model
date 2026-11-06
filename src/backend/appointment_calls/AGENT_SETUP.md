# ElevenLabs agent setup

Done once in your ElevenLabs account, before adding phone calls from the + menu.

1. Import your Twilio number into ElevenLabs and copy its phone number ID.
2. Create an agent and set its LLM to **Custom LLM**, pointing at your model's server. The server must offer a streaming, OpenAI-compatible `/v1/chat/completions` with function calling, be reachable by ElevenLabs, and require authentication.
   - **Temporary OpenAI option:** use `https://api.openai.com/v1` as the server URL, your chosen OpenAI model as the model ID, and your OpenAI key saved as an ElevenLabs secret. Remove this when your own model is ready.
3. Leave **Backup LLM** on Default or Disabled. With a custom LLM these don't fall back to hosted models. The app refuses an agent with a custom backup list, or any LLM other than Custom LLM.
4. Enable the `end_call` and `voicemail_detection` system tools. Don't leave a voicemail message.
5. Add these data collection fields:
   - `booked` (boolean): whether a reservation or appointment was agreed
   - `appointment_time` (string): the agreed start time in ISO 8601 with a UTC offset
   - `alternatives` (string): times offered that weren't accepted
   - `notes` (string): anything the owner needs to know, such as what to bring
6. Set the first message and system prompt below.

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
