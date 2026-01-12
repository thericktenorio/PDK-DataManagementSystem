# Apply Facade + Strategy + Adapter + Observer

Date: 2025-10-29

## Status

Acepted

## Context

I need clear orchestration, swappable algorithms, library isolation, and auditable events.

## Decision

- **Facade**: `PDFParserFacade` coordinates the pipeline.
- **Strategy**: page classification, field extraction, reorder rules behind interfaces & registries.
- **Adapter**: PDF/ OCR providers behind adapters.
- **Observer**: event bus + `AuditObserver` ot tee events to logging/DB.

## Consequences

- (+) High decoupling and testability.
- (+) Easy to A/B strategies and switch libraries.
- (-) More files/indirection; mitigated with registries and disciplined packaging.
