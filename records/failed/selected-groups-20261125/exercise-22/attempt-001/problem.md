# Exercise 22 — Conjugation preserves order

Task `exercise-22`. Split `train`. Source `data/training_questions.md` (SHA-256 `2619c9aeadc349114f8ebd39d67dfa7eb4ae268d82e6548626c54f47f26b5084`).

For $x,g\in G$, prove that

$$
|x|=|g^{-1}xg|.
$$

Deduce that

$$
|ab|=|ba|
\qquad\text{for all }a,b\in G.
$$

**Value:** Introduces conjugation as a structure-preserving operation. The statement
includes elements of infinite order.

Lean mapping: The conjunction retains both requested equalities. Lean's orderOf equals zero for elements of infinite order, so the same equality covers those elements.
