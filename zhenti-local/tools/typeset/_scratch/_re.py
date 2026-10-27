import re

opt = "D. Adopt new technology. Questions 5 to 8are based on the conversation you have just heard."
pats = [
    r"\s(Questions?\s+\d+\s*(?:to|and)\s*\d+\b.*)$",
    r"\sQuestions?\s+\d+\s*(?:to|and|-)\s*\d+",
    r"\bQuestions?\s+\d+",
]
for p in pats:
    print(p, "->", bool(re.search(p, opt)))
