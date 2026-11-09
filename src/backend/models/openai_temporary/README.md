# Temporary OpenAI model

Used to test the app until the owner's own model is ready. It serves only the picker's "Model" option, never Image Generation. While it's connected, OpenAI receives chat messages and tool results, including emails if Gmail is on.

The Control Panel's To Do scan also uses it in the background, without a chat. For each new email outside Gmail's Promotions and Social tabs, OpenAI receives the sender, subject and date, the titles and company names of tasks already listed, and up to 2,000 characters of the body when the rest isn't enough. Scans run every 5 minutes and cover up to 100 emails each.

## Turn it on

Add your chosen model to `.env`. There is no default.

```
OPENAI_MODEL=your-model-name
```

Save the API key in the keychain from the project folder, then restart the app. The key won't show as you type or paste it.

```
venv/bin/python -c "import getpass, keyring; keyring.set_password('local-model', 'OPENAI_API_KEY', getpass.getpass('OpenAI API key: '))"
```

## Remove it

1. Delete this folder and `tests/unit/test_openai_temporary.py`.
2. Remove the `openai_temporary` import and the `openai_temporary.connect()` line from `src/backend/main.py`.
3. Remove `OPENAI_MODEL` from `.env` and `OPENAI_API_KEY` from the keychain.
4. Delete the OpenAI key from your ElevenLabs agent and account, and point its Custom LLM at your own model's server.
5. Revoke the key in your OpenAI account. This is what actually ends its access.
6. Search the project for `openai` to confirm nothing is left behind, and check OpenAI's data controls for anything it already received, since deleting files here can't remove data held on its side.
