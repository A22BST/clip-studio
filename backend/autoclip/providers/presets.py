"""Provider buckets checked against the source notes on 2026-11-21.

Verified means the published pages were checked, not live API/account access.
Unknown request allowances stay unset; neuron/token budgets are not requests.
"""

PRESETS = {
    "zai-glm-flash": {
        "base_url": "https://api.z.ai/api/paas/v4/",
        "models": ["glm-4.7-flash", "glm-4.5-flash"],
        "notes": "Standard API Key required, separate from Coding Plan keys. Legacy free models "
        "may retire; lowercase IDs inferred. Limits only visible in console, not checked.",
    },
    "nvidia-nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "models": [
            "deepseek-ai/deepseek-v4-flash",
            "moonshotai/kimi-k3",
            "minimaxai/minimax-m3.1-flash",
        ],
        "notes": "Trial service; limits/credits not published on pages read. DeepSeek/Kimi IDs "
        "inferred from slugs; MiniMax research/dev licence. Trial terms PDF not read.",
    },
    "openrouter-free": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "nvidia/nemotron-3.5-super-vl:free",
            "baidu/ernie-5.5-flash-preview:free",
            "inclusionai/ling-3.2-flash:free",
            "recursive/flint-v1.0:free",
        ],
        "daily_requests": 50,
        "notes": "Shared allowance across free models, including failed calls; 20 RPM. "
        "1000 RPD needs purchased credits ($10 table/$9 FAQ). Gemma 31B absent from fetched "
        "top ten; Flint supplied by task, absent from notes. Never deny data_collection.",
    },
    "google-ai-studio": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"],
        "reset": "America/Los_Angeles",
        "notes": "Beta endpoint; per-model limits require logged-in console. Free content used "
        "to improve products per pricing; EEA exception unconfirmed, terms not read. "
        "gemini-2.5 IDs redirect 2026-12-01.",
    },
    "cloudflare-workers-ai": {
        "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "models": [
            "@cf/openai/gpt-oss-120b",
            "@cf/google/gemma-4-26b-a4b-it",
            "@cf/nvidia/nemotron-3-120b-a12b",
            "@cf/openai/gpt-oss-20b",
        ],
        "notes": "Requires cloudflare-account-id and Workers AI Read+Edit token. 10000 neurons "
        "per UTC day, not a request allowance; 300 RPM text. Kimi/GLM 5/DeepSeek paid only.",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"],
        "daily_requests": 1000,
        "max_prompt_tokens": 6000,
        "notes": "First rate-limit tab, probably Free: 30 RPM, 1000 RPD, 8K TPM, 200K TPD. "
        "6000 prompt estimate leaves some headroom; use small prompts. No Kimi listed.",
    },
    "aihubmix": {
        "base_url": "https://aihubmix.com/v1",
        "models": [
            "coding-glm-5.3-free",
            "coding-kimi-k3-free",
            "nemotron-3-ultra-550b-a55b-free",
            "gemma-4-31b-it-free",
        ],
        "daily_requests": 100,
        "notes": "Only 10 trial calls total before one-time $1 top-up; then shared 10 RPM, "
        "100 RPD, 1M tokens/day. Live limits at /call/free_quota_config; not no-payment.",
    },
    "pollinations": {
        "base_url": "https://gen.pollinations.ai/v1",
        "models": ["openai/gpt-oss-20b", "google/gemma-4-31b-it", "deepseek/deepseek-v4-flash"],
        "notes": "Bearer sk_* key required (secret pollinations). Balance-based billing (402); "
        "no global free allowance verified; 429/503 Retry-After. Old endpoint not rechecked.",
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "models": [],
        "notes": "Local final fallback; uses configured Ollama model. Runs only when existing "
        "job/lock indicators establish idle state; unknown state skips it.",
    },
}

for _name, _preset in PRESETS.items():
    _preset.setdefault("key_name", _name if _name != "ollama" else "")
    _preset.setdefault("daily_requests", None)
    _preset.setdefault("reset", "utc")
    _preset.update(verified=True, checked="2026-11-21")
