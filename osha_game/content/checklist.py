"""Inspect: one ordered checklist per module, built at bank-build time from 'rule' facts.
Phase 3 fills this in. Contract: build_and_insert(con, ctx) inserts into checklist_items
on the given bank connection and returns {'items': n, 'modules': m} (or {} if nothing)."""


def build_and_insert(con, ctx) -> dict:
    return {}
