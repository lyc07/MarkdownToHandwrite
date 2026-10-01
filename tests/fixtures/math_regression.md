# Generic mathematical rendering regression fixture

These self-contained examples exercise supported syntax without external files
or document-specific data. Both inline delimiter styles and display blocks are
intentional; the regression test parses and renders every formula.

## Inline expressions

Arithmetic: \(a+b=c\).

Powers: $a^2+b^2=c^2$.

Units and spacing: \(v=12\,\mathrm{m}\,\mathrm{s}^{-1}\).

Derivatives: $f'(x)+g''(x)=h^{\prime}(x)$.

Greek symbols: \(\alpha+\beta=\gamma,\quad\Delta x=\epsilon\).

Products and comparisons: $a\cdot b+c\times d\ne0$.

## Fractions, roots, scripts, and accents

$$
q=\frac{a+b}{c+d}
$$

$$
r=\frac{1}{1+\frac{1}{x}}
$$

$$
s=\sqrt{x^2+y^2}
$$

$$
t=\sqrt[3]{a+b}
$$

$$
a_{i+1}^{n-1}=b_i^n
$$

$$
\hat{x}+\bar{x}+\vec{v}+\dot{x}+\ddot{x}
$$

## Operators and elementary functions

$$
S_n=\sum_{i=1}^{n}i=\frac{n(n+1)}{2}
$$

$$
P_n=\prod_{k=1}^{n}k
$$

$$
I=\int_{0}^{1}x^2\,dx
$$

$$
J=\iint_D f(x,y)\,dx\,dy
$$

$$
\lim_{x\to0}\frac{\sin x}{x}=1
$$

$$
\sin^2 x+\cos^2 x=1
$$

$$
\ln(\exp x)=x
$$

$$
C=\binom{n}{k}
$$

## Sets, matrices, cases, and styles

$$
S=\{x\in\mathbb{R}\mid x\ge0\}
$$

$$
\forall x\in A,\quad\exists y\in B,\quad x\le y
$$

$$
A=\begin{bmatrix}a&b\\c&d\end{bmatrix}
$$

$$
u=\begin{pmatrix}x\\y\end{pmatrix}
$$

$$
f(x)=\begin{cases}x,&x\ge0\\-x,&x<0\end{cases}
$$

$$
\operatorname{rank}(A)\le\min(m,n)
$$

$$
\displaystyle\sum_{j=0}^{n}a_j
$$

$$
\left(a+b\right)^2=a^2+2ab+b^2
$$
