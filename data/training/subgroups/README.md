# Subgroups and homomorphisms

This training-only collection contains 11 worked Lean 4 exercises. Read
[exercises.jsonl](exercises.jsonl) for the paired statements, proofs and tactic
annotations. The [Lean file](../../../AI4Algebra/Benchmarks/Gold/ExternalSubgroups.lean)
contains the same solutions in dependency order under the protected Gold namespace.

| Exercise | Main proof idea |
| --- | --- |
| `map_mono` | Carry an image-membership witness through a subgroup inclusion. |
| `map_comp` | Prove equality of subgroup images by transporting witnesses in both directions. |
| `conjugate` | Construct the conjugate subgroup and prove all three closure laws. |
| `conjugate_mul` | Compose two conjugations and recover witnesses for the reverse inclusion. |
| `eq_bot_iff_card` | Characterize the trivial subgroup by uniqueness of its element. |
| `inf_bot_of_coprime` | Show the order of the intersection divides both orders, then use coprimality. |
| `aux_card_eq` | Compute the cardinality of a quotient using the subgroup index. |
| `iso₁` | Restrict the quotient homomorphism to a disjoint normal subgroup and prove bijectivity. |
| `iso₂` | Combine two quotient maps and use their kernels and cardinalities to prove bijectivity. |
| `map_inverse_from_mul` | Derive preservation of identity and inverses from multiplicativity. |
| `composeLinearMap` | Construct the composite linear map and discharge its two compatibility laws. |

Each UTF-8 JSON line has an English problem, a Lean statement or construction skeleton,
the complete local declaration (`solution_lean`), and its upstream source links.
`requires` lists earlier exercises used in the local declaration. Use the imports in
the row and the namespace and open declarations in the Lean file when replaying excerpts.

`tactics` follows the written proof in source order, including nested tactic blocks.
Line and column are one-based Unicode character positions within `solution_lean`.
`source_line_tail` starts at the tactic and extends to the last code on its line.
The complete declaration preserves continuations, branches, terms and indentation.
These are source annotations for future training. They contain no observed proof
states, rewards or model decisions. The collection is outside the active search
manifests. Keep the worked answers out of held-out evaluation and retrieval.

## Sources and adaptations

- The first nine exercises come from [*Mathematics in Lean*, Chapter 9](https://github.com/leanprover-community/mathematics_in_lean/blob/cff01285931648054c4fe6817baed0ccd45c0372/MIL/C09_Groups_and_Rings/solutions/Solutions_S01_Groups.lean).
  The local edition names anonymous exercises, makes section parameters explicit,
  and presents the multiplication law for the conjugation action as a theorem.
  [Apache 2.0 license](LICENSE-mil.txt).
- The multiplicativity exercise combines two [Leanlings Algebra homomorphism exercises](https://github.com/SamuelSchlesinger/leanlings/tree/b9472b17daa6b2e9b9f3afe88794c9fa7514a0f7/courses/algebra/solutions/Hom).
  The port takes an ordinary function with a multiplication law, so the identity
  and inverse laws must be derived. [MIT license](LICENSE-leanlings.txt).
- The linear-map exercise adapts [*Lean for Working Algebraists*, Chapter 11, exercise 2](https://github.com/abderrahim-lectures/lean4-learning/blob/230c6eaf6f9b15b5e6aeffed1ac35774ef627848/lean_book/15-appendix-solutions/11-chapter-11.md#L28-L48)
  to Mathlib's module and linear-map types. The [upstream notice](https://github.com/abderrahim-lectures/lean4-learning/blob/230c6eaf6f9b15b5e6aeffed1ac35774ef627848/NOTICE.md)
  describes the book's AI-assisted authorship. [MIT license](LICENSE-working.txt).

Run `python -m pytest -q tests/lean/test_external_subgroups.py` from the repository
root to check the JSONL against the Lean source, replay all declarations, and audit
their transitive axioms on the project's pinned toolchain.
