# Exercise 31 — An element of order two must exist

Task `exercise-31`. Split `train`. Source `data/training_questions.md` (SHA-256 `2619c9aeadc349114f8ebd39d67dfa7eb4ae268d82e6548626c54f47f26b5084`).

Prove that every finite group $G$ of even order contains an element of order $2$.

**Value:** Combines the inverse operation with a counting argument—a useful first
example of proving existence without explicitly constructing an element.

Lean mapping: Fintype.card G is the finite group order, and the witness must have exact order two.
