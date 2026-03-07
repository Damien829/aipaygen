"""TF-IDF Skills Search Engine — lightweight, no dependencies beyond stdlib"""
import math
import re
import sqlite3
import threading
from collections import Counter


STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most", "other",
    "some", "such", "no", "only", "own", "same", "than", "too", "very",
    "just", "because", "if", "when", "where", "how", "what", "which", "who",
    "whom", "this", "that", "these", "those", "it", "its", "i", "me", "my",
    "we", "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their", "about", "up", "also", "using", "use", "based", "via",
})


def _tokenize(text):
    """Split text into lowercase alphanumeric tokens, removing stop words."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP_WORDS]


class SkillsSearchEngine:
    def __init__(self, db_path="skills.db"):
        self.db_path = db_path
        self.index = {}          # term -> {doc_id: tf-idf weight}
        self.doc_norms = {}      # doc_id -> L2 norm of doc vector
        self.skills = {}         # doc_id -> skill dict
        self.idf = {}            # term -> idf value
        self._built = False
        self._lock = threading.Lock()

    def build_index(self):
        """Build inverted index from skills database."""
        with self._lock:
            if self._built:
                return

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, description, category, input_schema, calls FROM skills"
            ).fetchall()
            conn.close()

            if not rows:
                self._built = True
                return

            doc_tfs = {}
            for row in rows:
                skill = dict(row)
                doc_id = skill["id"]
                self.skills[doc_id] = skill

                name_tokens = _tokenize(skill["name"])
                desc_tokens = _tokenize(skill["description"] or "")
                cat_tokens = _tokenize(skill["category"] or "")

                tf = Counter()
                for t in name_tokens:
                    tf[t] += 2  # name tokens weighted 2x
                for t in desc_tokens:
                    tf[t] += 1
                for t in cat_tokens:
                    tf[t] += 1
                doc_tfs[doc_id] = tf

            N = len(doc_tfs)

            df = Counter()
            for tf in doc_tfs.values():
                for term in tf:
                    df[term] += 1

            self.idf = {term: math.log(N / count) for term, count in df.items()}

            self.index = {}
            self.doc_norms = {}
            for doc_id, tf in doc_tfs.items():
                max_tf = max(tf.values()) if tf else 1
                norm_sq = 0.0
                for term, raw_tf in tf.items():
                    normalized_tf = raw_tf / max_tf
                    weight = normalized_tf * self.idf.get(term, 0)
                    if weight > 0:
                        self.index.setdefault(term, {})[doc_id] = weight
                        norm_sq += weight * weight
                self.doc_norms[doc_id] = math.sqrt(norm_sq) if norm_sq > 0 else 1.0

            self._built = True

    def search(self, query, top_n=20):
        """Search skills using cosine similarity. Returns list of skill dicts with score."""
        if not self._built:
            self.build_index()

        query = query[:1000]
        tokens = _tokenize(query)
        if not tokens:
            return []

        query_tf = Counter(tokens)
        max_qtf = max(query_tf.values())
        query_weights = {}
        query_norm_sq = 0.0
        for term, raw_tf in query_tf.items():
            if term in self.idf:
                w = (raw_tf / max_qtf) * self.idf[term]
                query_weights[term] = w
                query_norm_sq += w * w

        if not query_weights:
            return []

        query_norm = math.sqrt(query_norm_sq)

        scores = Counter()
        for term, qw in query_weights.items():
            postings = self.index.get(term, {})
            for doc_id, dw in postings.items():
                scores[doc_id] += qw * dw

        results = []
        for doc_id, dot in scores.items():
            cosine = dot / (query_norm * self.doc_norms[doc_id])
            skill = dict(self.skills[doc_id])
            skill["score"] = round(cosine, 4)
            results.append(skill)

        results.sort(key=lambda x: (-x["score"], -x.get("calls", 0)))
        return results[:top_n]

    def invalidate(self):
        """Clear index (call after /skills/absorb)."""
        with self._lock:
            self._built = False
            self.index.clear()
            self.skills.clear()
            self.doc_norms.clear()
            self.idf.clear()
