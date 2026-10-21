## Project Name

> AirworthyAsk

Helps aircraft maintenance engineers find the latest DGCA Civil Aviation Requirement (CAR) and revision efficiently.

## Problem

Aircraft Maintenance Engineer (AME) trainees and technicians often study from outdated physical copies or old PDFs of regulations. DGCA Civil Aviation Requirements (CARs) are revised frequently, making it difficult to verify if a specific section is up to date during daily maintenance checks or exam preparation. Manually searching through multiple PDF documents and amendment lists is slow and error-prone. This product instantly indexes and retrieves the most recent DGCA CAR sections and their latest revisions, ensuring compliance and confidence.

---

## Who it is for

- Aircraft Maintenance Engineer (AME) trainees working at MRO hangars near airports (e.g., Chennai Airport).
- Certifying engineers and aviation regulatory exam aspirants needing fast, accurate access to current CAR revisions.

---

## Signature feature

Real-Time Section & Revision Lookup: Instantly search across all DGCA CAR sections to retrieve exact, up-to-date regulatory text along with explicit revision numbers and effective dates.

---

## Hardest problem (my interview story)

Parsing and tracking frequent, non-standardized revision updates published across various DGCA notification PDFs. Ensuring the search system prioritized the latest amendment over older versions required building an accurate metadata extraction pipeline to correctly identify section numbers, revision histories, and effective dates.

---

## Dataset

| Source | Link | Documents | Pages | Licence / terms |
| :--- | :--- | :--- | :--- | :--- |
| DGCA Official Website | [dgca.gov.in](https://dgca.gov.in) | Civil Aviation Requirements (CARs) | Variable | Public Domain / Open Government Data |

---

## 10 real questions

See docs/QUESTIONS.md.

---

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                 # Windows: copy .env.example .env
uvicorn app.main:app --reload
curl localhost:8000/health
```

---

## Live link

<Added in Week 2>
