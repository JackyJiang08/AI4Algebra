# Reference solutions for the selected group theory exercises

Provided by the user for reference. Exercise numbering matches
[the selected questions](../../../data/training_questions.md).
These solutions are protected reference material: they are not proof-search inputs,
candidate prompts, replay samples, or return-memory entries. Reference proof checks
must be reported separately from autonomous proof-search results.

## Exercise 11 — Computing element orders

The order of $\bar{k}\in\mathbb Z/12\mathbb Z$ is the least positive integer $m$
such that $12\mid mk$. If $d=\gcd(12,k)$, then $12/d$ and $k/d$ are coprime, so
$12\mid mk$ exactly when $12/d\mid m$. Thus
$\lvert\bar{k}\rvert=12/\gcd(12,k)$.

| Representative $k$ | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Order | 1 | 12 | 6 | 4 | 3 | 12 | 2 | 12 | 3 | 4 | 6 | 12 |

## Exercise 16 — Recognizing elements of order two

If $x^2=1$, then the least positive exponent $m$ for which $x^m=1$ is at most $2$,
so $|x|$ is $1$ or $2$.

Conversely, if $|x|=1$, then $x=1$ and hence $x^2=1$. If $|x|=2$, then $x^2=1$
by definition.

## Exercise 15 — Inverting a product

Proceed by induction on $n$. For $n=1$, the formula is immediate. Assume it holds
for $n=k$ and put $P=a_1\cdots a_k$. Then

$$
(Pa_{k+1})(a_{k+1}^{-1}P^{-1})
=P(a_{k+1}a_{k+1}^{-1})P^{-1}=1.
$$

Thus $(Pa_{k+1})^{-1}=a_{k+1}^{-1}P^{-1}$. Substituting
$P^{-1}=a_k^{-1}\cdots a_1^{-1}$ gives the formula for $n=k+1$.

## Exercise 26 — The subgroup criterion

Closure under multiplication makes the restricted operation a binary operation on
$H$, and associativity is inherited from $G$. Since $H$ is nonempty, choose $h\in H$.
Closure under inverses and products gives $h^{-1}\in H$ and $hh^{-1}=1\in H$.
This identity acts on $H$ as it does on $G$, and every element of $H$ has its inverse
in $H$ by hypothesis. Hence $H$ is a subgroup of $G$.

## Exercise 27 — Constructing a cyclic subgroup

Let $H=\{x^n\mid n\in\mathbb Z\}$. Since $x^0=1$, the set $H$ is nonempty.
For integers $m,n$, the power laws give

$$
x^m x^n=x^{m+n}\in H
\qquad\text{and}\qquad
(x^m)^{-1}=x^{-m}\in H.
$$

The subgroup criterion from Exercise 26 now shows that $H$ is a subgroup of $G$.

## Exercise 25 — A condition forcing commutativity

The hypothesis $x^2=1$ implies $x^{-1}=x$ for every $x\in G$. Applying this to $a$,
$b$, and $ab$ gives

$$
ab=(ab)^{-1}=b^{-1}a^{-1}=ba.
$$

Since $a$ and $b$ were arbitrary, $G$ is abelian.

## Exercise 9 — Groups built from $\sqrt{2}$

Let $S=\{a+b\sqrt{2}\mid a,b\in\mathbb Q\}$.

**(a) Addition.** The sum of two elements of $S$ is

$$
(a+b\sqrt{2})+(c+d\sqrt{2})=(a+c)+(b+d)\sqrt{2}\in S.
$$

The identity is $0=0+0\sqrt{2}$, the inverse of $a+b\sqrt{2}$ is
$-a-b\sqrt{2}$, and associativity is inherited from $\mathbb R$. Thus $S$ is a
group under addition.

**(b) Multiplication.** The product of two elements of $S$ is

$$
(a+b\sqrt{2})(c+d\sqrt{2})=(ac+2bd)+(ad+bc)\sqrt{2}\in S.
$$

A product of nonzero real numbers is nonzero, so $S\setminus\{0\}$ is closed under
multiplication. For a nonzero $a+b\sqrt{2}$, its reciprocal is

$$
\frac{1}{a+b\sqrt{2}}
=\frac{a}{a^2-2b^2}-\frac{b}{a^2-2b^2}\sqrt{2}.
$$

The denominator is nonzero. If $b=0$, then $a\ne0$. If $b\ne0$ and the denominator
were zero, then $|a/b|=\sqrt{2}$ would be rational. The reciprocal therefore has
rational coefficients and belongs to $S\setminus\{0\}$. With identity $1$ and
associativity inherited from $\mathbb R$, this set is a group under multiplication.

## Exercise 23 — Orders of powers

Suppose $|x|=st$ with $s,t>0$. Since $(x^s)^t=x^{st}=1$, the order $r=|x^s|$ exists
and satisfies $r\le t$. Also, $x^{sr}=(x^s)^r=1$. The minimality of $st$ as the
positive exponent giving $1$ for $x$ implies $sr\ge st$, so $r\ge t$. Therefore
$|x^s|=t$.

## Exercise 22 — Conjugation preserves order

For every positive integer $k$,

$$
(g^{-1}xg)^k=g^{-1}x^kg.
$$

The identity holds for $k=1$. For the induction step, multiplying $g^{-1}x^kg$ by
$g^{-1}xg$ cancels the middle $gg^{-1}$, leaving $g^{-1}x^{k+1}g$.

It follows that $(g^{-1}xg)^k=1$ exactly when $x^k=1$. The two elements therefore
have the same least positive exponent giving $1$, or both have infinite order.
Finally, $b(ab)b^{-1}=ba$, so $ab$ and $ba$ are conjugate and have the same order.

## Exercise 31 — An element of order two must exist

Let $T=\{g\in G\mid g\ne g^{-1}\}$. Each element of $T$ belongs to a pair
$\{g,g^{-1}\}$ of distinct elements, and these pairs partition $T$. Thus $|T|$ is even.

Since $|G|$ is even, $|G\setminus T|$ is also even. The identity belongs to
$G\setminus T$, so this set contains at least one other element $a$. Then
$a=a^{-1}$, which gives $a^2=1$. Since $a\ne1$, its order is exactly $2$.
