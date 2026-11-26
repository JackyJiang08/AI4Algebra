# Exercise 26 — The subgroup criterion

Task `exercise-26`. Split `train`. Source `data/training_questions.md` (SHA-256 `2619c9aeadc349114f8ebd39d67dfa7eb4ae268d82e6548626c54f47f26b5084`).

Suppose $H$ is a nonempty subset of $G$ that is closed under multiplication and
inverses: for every $h,k\in H$, both $hk\in H$ and $h^{-1}\in H$.

Prove that $H$ is a group under the operation inherited from $G$. Such a subset is
called a subgroup of $G$.

**Value:** Establishes a reusable method for proving that a subset forms a group.

Lean mapping: A subgroup with carrier H supplies the group structure inherited from G. Nonemptiness and both closure assumptions are explicit.
