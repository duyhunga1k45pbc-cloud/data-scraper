# Data Scraper — M0 Architecture Contract

## 1. Scope

M0 targets **Books to Scrape**.

The purpose of M0 is not to build a generic scraping framework. It is to build one trustworthy observation-to-state loop for a simple product-like domain, then use a later real e-commerce source to discover what actually generalizes.

## 2. Business goal

> Collect external book data and maintain a reliable structured state and history.

Core business flow:

```text
Acquire
→ Structure
→ Data State
→ History
→ Deliver
```

### Business requirements

**BR-01 — Acquire**  
Collect book records inside the configured source scope.

**BR-02 — Structure**  
Extract and normalize the required fields into a defined schema.

**BR-03 — Data State**  
Make it possible to explain which representation the data is in, whether it is accepted for persistence, and why.

**BR-04 — Current trusted state**  
Maintain the current trusted representation of each book. Invalid or failed data must not silently overwrite trusted state.

**BR-05 — History**  
Preserve accepted trusted state transitions so that state evolution can be explained.

**BR-06 — Deliver**  
Expose current state and history as structured data for downstream use.

## 3. Core architecture

```text
External Source
      ↓
    Fetch
      ↓
┌─────────────────┐
│   RawEvidence   │
│ exact response  │
└────────┬────────┘
         ↓ extract
┌─────────────────┐
│ BookObservation │
│ source-shaped   │
└────────┬────────┘
         ↓ normalize
┌────────────────────┐
│ BookNormalizedData │
└─────────┬──────────┘
          ↓ validate
┌─────────────────┐
│  ValidatedBook  │
└────────┬────────┘
         ↓
  State Transition
   ┌─────┼───────────┐
   │     │           │
 CREATE NO_CHANGE   UPDATE
   │                 │
   └────────┬────────┘
            ↓
   CurrentBookState
            ↓
       BookHistory
            ↓
         Deliver
```

If validation fails:

```text
BookNormalizedData
        ↓
 validation failed
        ↓
      REJECT
        ↓
current state unchanged
history unchanged
```

## 4. Representation boundaries

The following are deliberately different representations:

```text
RawEvidence
!= BookObservation
!= BookNormalizedData
!= ValidatedBook
!= CurrentBookState
```

A representation becoming parseable does not imply that it is valid, and valid data does not imply that it must change state.

### 4.1 RawEvidence

Purpose:

> Preserve the exact input required to verify and reproduce extraction.

Minimum M0 fields:

```text
id
source_url
fetched_at
status_code
content_type
body
body_hash
```

`body` is the exact response content used by the parser.

`body_hash` may identify or compare content, but it does not replace the body because a hash cannot reproduce extraction.

Raw evidence is append-oriented in the normal application flow. Existing evidence is not rewritten as part of normal processing.

### 4.2 BookObservation

Represents what the extractor observed from the evidence, as close to the source representation as practical.

Minimum M0 fields:

```text
evidence_id
extractor_version
source_url
observed_at

title_raw
price_raw
availability_raw
category_raw
```

Example:

```text
price_raw = "£51.77"
availability_raw = "In stock (22 available)"
```

An observation is not yet trusted business data.

### 4.3 BookNormalizedData

Normalization changes representation but does not decide whether the result has valid domain meaning.

Examples:

```text
"£51.77"
→ price = Decimal("51.77")
→ currency = GBP
```

```text
"In stock (22 available)"
→ availability = IN_STOCK
→ quantity = 22
```

Conceptual M0 fields:

```text
title
price
currency
availability
quantity
category
canonical_product_url
```

Core rule:

> Parseable != Valid

### 4.4 ValidatedBook

`ValidatedBook` exists only after normalized data satisfies the M0 domain validation rules.

It is the boundary into state-transition logic:

> Only ValidatedBook may enter state-transition logic.

### 4.5 CurrentBookState

`CurrentBookState` is the current trusted representation of a book.

It is not simply the latest scraped value.

Conceptual fields:

```text
identity
title
price
currency
availability
quantity
category
source_url
observed_at
updated_at
```

### 4.6 BookHistory

History contains accepted trusted state transitions only.

A failed scrape, failed normalization, or rejected validation is not a business state transition.

## 5. Validation

Validation protects the meaning of data before it is allowed to influence trusted state.

### 5.1 Field validation

**Title**

```text
must exist
must not be empty
```

**Price**

```text
must exist
must be representable as Decimal
must be >= 0
```

**Currency**

```text
must be recognized
```

**Availability**

```text
must map to a recognized state
```

**Quantity**

```text
if present, must be >= 0
```

### 5.2 Cross-field consistency

Fields that are individually valid must also be semantically consistent together.

Example:

```text
availability = OUT_OF_STOCK
quantity = 22
→ invalid
```

Another example when currency is required for a price:

```text
price = 51.77
currency = missing
→ invalid
```

### 5.3 Identity validity

M0 does not have a separate identity-resolution subsystem.

Identity is:

```text
source + canonical_product_url
```

Validation checks only what M0 needs:

```text
source is known
canonical product URL exists
URL can be normalized into the expected form
```

URL migration, fuzzy matching, and cross-source identity resolution are explicitly outside M0.

## 6. Data State

Data State answers:

> What representation is this data currently in, is it allowed to become persisted trusted state, and why?

Example:

```text
price_raw = "-£51.77"
        ↓
normalized
price = -51.77 GBP
        ↓
validation
NEGATIVE_PRICE
        ↓
REJECT
        ↓
CurrentBookState unchanged
BookHistory unchanged
```

The system should be able to explain:

```text
Rejected because NEGATIVE_PRICE
```

rather than only reporting a generic failure.

## 7. State transition rules

State-transition behavior is part of the core architecture.

### ST-01 — Create

```text
No existing current state
+
ValidatedBook
        ↓
CREATE CurrentBookState
+
APPEND initial history
```

### ST-02 — No change

```text
Existing CurrentBookState
+
same ValidatedBook
        ↓
NO_CHANGE
state unchanged
history unchanged
```

### ST-03 — Update

```text
Existing CurrentBookState
+
different ValidatedBook
        ↓
UPDATE CurrentBookState
+
APPEND history
```

### ST-04 — Reject invalid data

```text
Existing CurrentBookState
+
validation failure
        ↓
REJECT
state unchanged
history unchanged
```

Conceptually:

```text
S(t+1) = S(t)     when input is invalid
S(t+1) = S(t)     when validated input is unchanged
S(t+1) = S(new)   when a validated change is accepted
```

## 8. Invariants

### INV-01

Only validated and accepted data may modify trusted persisted state.

### INV-02

Invalid or failed data must not modify current trusted state.

### INV-03

One M0 source identity has at most one current book state.

### INV-04

Persisted current state must satisfy the domain validation rules.

### INV-05

Current-state update and history append form one logical atomic transition.

A successful state change without corresponding history, or history that claims a change not reflected by current state, is invalid system behavior.

### INV-06

Reprocessing the same effective state must not create duplicate state transitions or duplicate history.

### INV-07

History must not contain a transition that trusted state never actually underwent.

## 9. Persistence M0

M0 persists four kinds of data:

```text
raw_evidence
      ↓
book_observations
      ↓ accepted
    books
      ↓
book_history
```

Their meanings are distinct:

| Persisted representation | Question it answers |
|---|---|
| `raw_evidence` | What exact response did the source return? |
| `book_observations` | What did the extractor/process interpret from that evidence? |
| `books` | What does the system currently trust? |
| `book_history` | How did trusted state actually change? |

Persistence design must preserve the invariants above, especially the atomic relationship between current-state updates and history.

### 9.1 Implemented persistence contract

M0 persistence uses the four tables above without introducing a generic repository or entity framework.

`book_observations` stores both source-shaped and normalized values, plus the state decision and validation errors. This preserves the divergence path through observation, normalization, and validation while keeping the persistence model at four tables.

`books.accepted_observation_id` identifies the observation that produced the current trusted state. A `NO_CHANGE` or `REJECT` observation does not replace that provenance.

`book_history.observation_id` identifies the observation that caused each accepted `CREATE` or `UPDATE` transition.

For `CREATE` and `UPDATE`, current-state mutation and history append are committed in the same database transaction to enforce INV-05. Raw evidence is committed before extraction/state persistence so the exact external input remains available even if a later processing step fails.

## 10. Divergence tracing

The architecture must allow a result to be traced backward through the representation chain:

```text
BookHistory
     ↑
CurrentBookState
     ↑
State Decision
     ↑
ValidatedBook
     ↑
BookNormalizedData
     ↑
BookObservation
     ↑
RawEvidence
```

Examples:

```text
RawEvidence:    £51.77
Observation:    £15.77
```

Divergence is at extraction.

```text
Observation:    £51.77
Normalized:     15.77 GBP
```

Divergence is at normalization.

```text
Normalized:     -51.77 GBP
Validation:     VALID
```

Divergence is at validation.

```text
ValidatedBook:  45.00 GBP
Persisted state:51.77 GBP
```

Divergence is in state-transition or persistence behavior.

The goal is end-to-end divergence tracing from exact external evidence to trusted state and history.

## 11. Acceptance criteria

Acceptance tests are executable evidence that the architecture behaves as specified. They assert business behavior rather than internal class/function structure.

### AC-01 — Valid new book

```text
Given no existing book
When a valid £51.77 observation is processed
Then current state is created with price £51.77
And initial history exists
```

### AC-02 — Idempotent same state

```text
Given current price = £51.77
When the same valid data is processed again
Then current state is unchanged
And no additional history entry is created
```

### AC-03 — Invalid negative price

```text
Given current price = £51.77
When normalized price = -£10
Then validation rejects the data
And current price remains £51.77
And history remains unchanged
```

### AC-04 — Missing required price

```text
Given current price = £51.77
When a required price cannot be produced
Then the data is rejected
And current state remains £51.77
And history remains unchanged
```

### AC-05 — Valid state transition

```text
Given current price = £51.77
When valid price = £45.00 is processed
Then current price becomes £45.00
And exactly one history transition is appended
```

### AC-06 — Evidence-to-observation correspondence

```text
Given raw evidence containing price £51.77
When extraction runs
Then the resulting observation must correspond to £51.77
```

### AC-07 — Atomic state/history rollback

```text
Given current price = £51.77
When a valid £45.00 update reaches persistence
And history append fails after the current-state row has been updated in the transaction
Then the entire state transaction rolls back
And current price remains £51.77
And no new history entry exists
And no accepted observation from the failed transaction remains
And the exact RawEvidence remains persisted for audit/replay
```

### AC-08 — Live source to persisted state trace

```text
Given the live Books to Scrape product page and PostgreSQL
When the full M0 pipeline runs
Then the persisted current state and history are traceable
through the accepted observation to the exact RawEvidence
captured from the live source
```

### AC-09 — CLI delivery

```text
Given a persisted trusted book state and history
When a downstream user invokes the M0 CLI
Then `show` returns the current trusted state
And `history` returns accepted state transitions
And `scrape` runs the live acquisition-to-persistence path and reports its state decision
```

The CLI is a delivery mechanism only. It must not duplicate validation or state-transition rules; it composes the existing acquisition, domain, and persistence services.

## 12. M0 code boundaries

Initial code structure:

```text
src/
├── acquisition/
│   └── fetch.py
│
├── books/
│   ├── parser.py
│   ├── observation.py
│   ├── normalization.py
│   ├── validation.py
│   ├── state.py
│   └── models.py
│
├── storage/
│   ├── models.py
│   └── repositories.py
│
└── main.py              # CLI delivery composition only

tests/
```

This is not a generic framework boundary. It is only the M0 implementation boundary for Books to Scrape.

## 13. M0 technology

Planned mechanisms:

```text
Python
httpx
BeautifulSoup + lxml
Pydantic
PostgreSQL
SQLAlchemy
Alembic
pytest
```

A mechanism should only be introduced when the architecture currently requires it.

## 14. Explicit M0 non-goals

Do not introduce these in M0 without new evidence that they are required:

```text
GenericEntity
BaseSourceAdapter
plugin architecture
generic domain model
fuzzy identity resolution
cross-source entity resolution
Redis
Celery
Playwright
LLM extraction
alerts
dashboards
```

## 15. Development loop

The project follows this loop:

```text
Business Requirements
        ↓
Data Meaning
        ↓
Validation
        ↓
Invariants
        ↓
State Transition Rules
        ↓
Architecture
        ↓
Acceptance Tests
        ↓
Run against reality
        ↓
Observed Failure Modes
        ↓
Architecture evolves only if required
```

Failure modes are not exhaustively invented in advance. Once the core architecture runs against real inputs, observed failures are used to test whether a requirement, invariant, validation rule, or mechanism must change.

## 16. Freeze rule

A new mechanism is added only when at least one of the following is true:

```text
new business requirement
OR
observed failure mode
OR
current mechanism cannot preserve an invariant
```

Do not add infrastructure, abstractions, or frameworks merely because they are common, modern, or potentially useful later.

## 17. M0 freeze point

This document is the M0 architecture contract.

The next implementation step is to create the minimal code skeleton and acceptance tests that make this contract executable.

After M0 works against Books to Scrape, a real e-commerce source should be used to reveal which abstractions are actually shared before any generic framework is introduced.


