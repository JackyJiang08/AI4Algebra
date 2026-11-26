# Exercise 9 — Groups built from √2

Task `exercise-9`. Split `train`. Source `data/training_questions.md` (SHA-256 `2619c9aeadc349114f8ebd39d67dfa7eb4ae268d82e6548626c54f47f26b5084`).

Let

$$
G=\{a+b\sqrt{2}\in\mathbb{R}\mid a,b\in\mathbb{Q}\}.
$$

(a) Prove that $G$ is a group under addition.

(b) Prove that $G\setminus\{0\}$ is a group under multiplication.

**Value:** Practices closure and explicit inverse construction, preparing for field extensions.

Lean mapping: The additive subgroup's carrier is exactly the specified real set. Real units correspond to nonzero real numbers via coercion and Units.mk0. The multiplicative subgroup's carrier therefore represents exactly the nonzero elements of the set, with multiplication inherited from the reals.
