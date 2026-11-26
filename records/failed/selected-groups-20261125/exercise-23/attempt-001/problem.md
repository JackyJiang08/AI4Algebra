# Exercise 23 — Orders of powers

Task `exercise-23`. Split `train`. Source `data/training_questions.md` (SHA-256 `2619c9aeadc349114f8ebd39d67dfa7eb4ae268d82e6548626c54f47f26b5084`).

Suppose $x\in G$ has finite order $n$. If $n=st$ for positive integers $s,t$, prove that

$$
|x^s|=t.
$$

**Value:** Develops the distinction between finding an exponent that gives the
identity and proving that exponent is minimal.

Lean mapping: The source order n is written as s * t. Positivity of both factors makes the order finite.
