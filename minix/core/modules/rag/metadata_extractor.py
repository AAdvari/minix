# LLM-powered structured metadata extraction from document text.
import json
import re
from minix.core.modules.rag.config import RagConfig
from minix.core.modules.rag.llm_factory import make_llm_client


_PROMPTS: dict[str, str] = {
    "cv": """\
Read the following document — it is a CV / resume.
Extract the following fields and return ONLY a valid JSON object.

Fields to extract (use null if not found):
{
  "candidate_name":   string,
  "email":            string,
  "phone":            string,
  "current_role":     string,
  "current_company":  string,
  "years_experience": number,
  "skills":           [string],
  "education":        [string],
  "languages":        [string],
  "location":         string,
  "summary":          string
}

Return ONLY the JSON object, no explanation.""",

    "contract": """\
Read the following document — it is a legal contract.
Extract the following fields and return ONLY a valid JSON object.

Fields to extract (use null if not found):
{
  "parties":          [string],
  "contract_type":    string,
  "effective_date":   string,
  "expiry_date":      string,
  "governing_law":    string,
  "key_obligations":  [string],
  "summary":          string
}

Return ONLY the JSON object, no explanation.""",

    "report": """\
Read the following document — it is a report or analysis.
Extract the following fields and return ONLY a valid JSON object.

Fields to extract (use null if not found):
{
  "title":        string,
  "authors":      [string],
  "date":         string,
  "topics":       [string],
  "key_findings": [string],
  "summary":      string
}

Return ONLY the JSON object, no explanation.""",

    "general": """\
Read the following document.
Extract the following fields and return ONLY a valid JSON object.

Fields to extract (use null if not found):
{
  "title":    string,
  "authors":  [string],
  "date":     string,
  "topics":   [string],
  "entities": [string],
  "summary":  string
}

Return ONLY the JSON object, no explanation.""",
}


class MetadataExtractor:

    def __init__(self):
        self._client = make_llm_client()
        self._model = RagConfig.DOCUMENT_PROCESSOR_MODEL

    @staticmethod
    def _detect_type(text: str) -> str:
        t = text[:3000].lower()
        cv_hits = sum(1 for kw in [
            "curriculum vitae", "resume", "work experience", "employment history",
            "education", "skills", "objective", "references available",
        ] if kw in t)
        contract_hits = sum(1 for kw in [
            "agreement", "whereas", "hereby", "indemnif", "governing law",
            "jurisdiction", "arbitration", "breach", "termination", "party",
        ] if kw in t)
        report_hits = sum(1 for kw in [
            "executive summary", "abstract", "methodology", "findings",
            "conclusion", "recommendation", "analysis", "figure", "table",
        ] if kw in t)
        best = max(cv_hits, contract_hits, report_hits)
        if best == 0:
            return "general"
        if best == cv_hits:
            return "cv"
        if best == contract_hits:
            return "contract"
        return "report"

    def extract(self, text: str, document_type: str | None = None) -> dict[str, str]:
        detected = document_type or self._detect_type(text)
        prompt = _PROMPTS.get(detected, _PROMPTS["general"])
        excerpt = text[:4000].strip()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": excerpt},
                ],
            )
            raw = response.choices[0].message.content.strip()
            parsed = self._parse_json(raw)
            result = self._flatten(parsed)
        except Exception:
            result = {}
        result["_detected_type"] = detected
        return result

    @staticmethod
    def _parse_json(raw: str) -> dict:
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        if match:
            raw = match.group(1)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _flatten(data: dict) -> dict[str, str]:
        flat: dict[str, str] = {}
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, list):
                joined = ", ".join(str(v) for v in value if v)
                if joined:
                    flat[key] = joined
            elif isinstance(value, (int, float)):
                flat[key] = str(value)
            elif isinstance(value, str) and value.strip():
                flat[key] = value.strip()
        return flat
