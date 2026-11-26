## 3. Exercise 15 — Inverting a product · Easy–moderate

Prove that, for all $a_1,a_2,\ldots,a_n\in G$,

$$
(a_1a_2\cdots a_n)^{-1}
=
a_n^{-1}a_{n-1}^{-1}\cdots a_1^{-1}.
$$

**Value:** Develops induction and careful manipulation of products in noncommutative groups.

Lean mapping: List.prod is ordered and works for a noncommutative group. The empty list has product one.
