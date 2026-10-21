# <Your product name>

> Fill this top section from your Examate project card on Day 1. Replace every line in angle brackets.

## Problem
<3–5 sentences: who struggles with what today, and what your product changes.>

## Who it is for
<One or two real user types, for example "compliance officer at a gold-loan NBFC in Coimbatore".>

## Signature feature
<One sentence: the feature only your product has.>

## Hardest problem (my interview story)
<In your own words, from your project card.>

## Dataset
| Source | Link | Documents | Pages | Licence / terms |
|---|---|---|---|---|
| <name> | <url> | <n> | <n> | <licence> |

## 10 real questions
See [docs/QUESTIONS.md](docs/QUESTIONS.md).

## Run it
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                 # Windows: copy .env.example .env
uvicorn app.main:app --reload
curl localhost:8000/health
```

## Live link
<Added in Week 2>
