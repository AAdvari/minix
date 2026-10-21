# Refusal classification for RAG answers: a regex heuristic that tags an
# answer as a refusal and says why (out_of_corpus / out_of_scope /
# policy_violation). Runs on every /query response, so it is regex-only — no
# model or tokenizer load on the answer path.
import re


# Cheap prompt-injection heuristic. Catches the obvious attempts that don't
# even need a model. Kept regex-only because the refusal classifier below
# calls it on every query and must not load a tokenizer.
INJECTION_PATTERNS = [
    # Classic "ignore previous" family (also catches "disregard / forget").
    r"ignore (?:all )?(?:previous|prior|above|earlier) instructions?",
    r"disregard (?:all |the |your )?(?:previous |prior |above )?(?:rules|instructions|guidelines|prompts?)",
    r"forget (?:all )?(?:previous|prior|above|earlier) (?:instructions?|context|prompts?)",

    # System-prompt extraction.
    r"(?:reveal|print|output|dump|leak|show|repeat|echo) (?:the |your )?(?:system|raw|hidden|initial|original) (?:prompt|instructions?|message)",
    r"what (?:are |is )?your (?:system )?(?:instructions|prompt|rules)",

    # Persona / role-play hijacking.
    r"you are now (?:a |an )?(?:different|new|unrestricted)",
    r"act as (?:if you (?:were|are) )?(?:a different|developer mode|dan|jailbroken|unrestricted)",
    r"pretend (?:to be|you are) (?:a |an )?(?:different|new|unrestricted)",
    r"from now on,? you (?:are|will|must)",

    # Bypass / safety-off requests.
    r"bypass (?:the |your |all )?(?:rules|safety|filter|guardrails?|restrictions?)",
    r"(?:turn off|disable|deactivate) (?:safety|filter|guardrails?|restrictions?)",
    r"without (?:any )?(?:restrictions?|filters?|limits?)",

    # Code / markdown injection tricks (instructions hidden in fenced blocks).
    r"```\s*(?:system|instructions?)",
    r"<\|im_(?:start|end)\|>",  # OpenAI chat format leak attempt
    r"<system>", r"</system>",

    # Multi-language "ignore previous" (Spanish, French, German, Chinese).
    r"ignora (?:todas |las )?instrucciones (?:anteriores|previas)",
    r"ignorez (?:toutes )?les instructions (?:précédentes|préalables)",
    r"ignoriere (?:alle )?(?:vorherigen|vorigen) (?:anweisungen|anleitungen)",
    r"忽略(?:之前|上面|所有)?(?:的)?指示",  # 忽略...指示
]


def looks_like_injection(text: str) -> bool:
    """Regex-only injection check. Used by `infer_refusal_reason` below —
    keep the signature stable."""
    t = (text or "").lower()
    return any(re.search(p, t) for p in INJECTION_PATTERNS)


REFUSAL_PATTERNS = [
    r"i do(?:n['’]| no)t have enough information",
    r"insufficient (?:context|information)",
    r"not (?:found|available|present) in (?:the )?context",
    r"no (?:relevant )?information (?:about|on|regarding|available)",
    r"cannot (?:answer|determine|provide)",
    r"unable to (?:answer|determine)",
    r"the (?:context|document|information) do(?:es)?n['’]?t (?:contain|include|mention)",
]


def is_refusal(answer: str) -> bool:
    a = (answer or "").lower()
    return any(re.search(p, a) for p in REFUSAL_PATTERNS)


def infer_refusal_reason(
    question: str,
    answer: str,
    selected_chunks: list[dict],
    retrieved_chunks: list[dict] | None = None,
) -> str | None:
    """Return one of: None | out_of_corpus | out_of_scope | policy_violation | ambiguous.

    Classification order:
      1. policy_violation — question contains a known prompt-injection pattern
         AND the LLM refused (don't flag benign questions).
      2. out_of_corpus — refused AND retrieval returned nothing at all
         (either no chunks made it past the relevance threshold, or the
         keyword/vector searches returned empty lists).
      3. out_of_scope — refused but SOME chunks were retrieved. The scope
         didn't match the question.
      4. None — LLM gave a substantive answer; no refusal detected.

    `retrieved_chunks` is optional — when provided it disambiguates between
    "filter wiped everything" (out_of_corpus) and "filter kept nothing but
    retrieval got some" (also out_of_corpus, because threshold said so).
    """
    if looks_like_injection(question) and is_refusal(answer):
        return "policy_violation"
    if not is_refusal(answer):
        return None
    if not selected_chunks:
        return "out_of_corpus"
    return "out_of_scope"
