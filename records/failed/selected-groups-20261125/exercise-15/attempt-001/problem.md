# Exercise 15 — Inverting a product

Task `exercise-15`. Split `train`. Source `data/training_questions.md` (SHA-256 `2619c9aeadc349114f8ebd39d67dfa7eb4ae268d82e6548626c54f47f26b5084`).

Prove that, for all $a_1,a_2,\ldots,a_n\in G$,

$$
(a_1a_2\cdots a_n)^{-1}
=
a_n^{-1}a_{n-1}^{-1}\cdots a_1^{-1}.
$$

**Value:** Develops induction and careful manipulation of products in noncommutative groups.

Lean mapping: List.prod is ordered and works for a noncommutative group. The empty list has product one.
