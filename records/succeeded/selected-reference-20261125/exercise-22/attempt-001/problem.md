## 9. Exercise 22 — Conjugation preserves order · Moderate–hard

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
