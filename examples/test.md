 $$E_B(X)  =\displaystyle \sum_{i=0}^{m-n} i \cdot \frac{C_{m-n}^i \cdot t^{i} \cdot (1-t)^{m-i}}{\sum_{j=0}^{m-n}C_{m-n}^j\cdot t^{j} \cdot (1-t)^{m-j}}$$
 这是一个需要利用坐标系旋转和巧妙划分积分区域来简化的二重积分题目。以下是详细的计算步骤：

### 1. 坐标系旋转变换

观察被积函数中的 $\frac{x+y}{\sqrt{2}}$ 项，我们可以作一个旋转正交变换来简化表达式。令：

$$u = \frac{x+y}{\sqrt{2}}, \quad v = \frac{-x+y}{\sqrt{2}}$$

由于该变换是旋转变换（旋转了 $45^\circ$），其雅可比行列式的绝对值为 $|J| = 1$。
同时，容易验证 $x^2 + y^2 = u^2 + v^2$。

原积分区域 $D = \{(x,y) \mid x^2 + y^2 \le 1\}$ 在新的坐标系下形状和大小保持不变，依然是单位圆盘：

$$D' = \{(u,v) \mid u^2 + v^2 \le 1\}$$

原积分即可化为：

$$I_2 = \iint_{D'} |u - (u^2 + v^2)| \, du dv$$

### 2. 去除绝对值符号

我们需要判断被积函数 $f(u,v) = u - u^2 - v^2$ 在积分区域内的正负性。
令 $u - u^2 - v^2 \ge 0$，通过配方可得：

$$\left(u - \frac{1}{2}\right)^2 + v^2 \le \frac{1}{4}$$

这表示一个圆心在 $(\frac{1}{2}, 0)$，半径为 $\frac{1}{2}$ 的小圆盘区域，我们将其记为 $D_1$。
显然，圆盘 $D_1$ 是完全包含在单位圆盘 $D'$ 内部的（两圆相内切于 $(1,0)$ 点）。

利用绝对值的性质或者通过区域拆分，我们可以将原积分转化为更易计算的形式：

$$\begin{aligned}
I_2 &= \iint_{D_1} (u - u^2 - v^2) \, du dv - \iint_{D' \setminus D_1} (u - u^2 - v^2) \, du dv \\
&= 2 \iint_{D_1} (u - u^2 - v^2) \, du dv - \iint_{D'} (u - u^2 - v^2) \, du dv
\end{aligned}$$

这种“补齐”整个大圆盘的转化方法可以避免处理复杂的边界拼接，只需分别计算两个完整圆盘区域上的积分即可。

### 3. 分别计算积分

**首先计算整个单位圆盘 $D'$ 上的积分：**

$$\iint_{D'} (u - u^2 - v^2) \, du dv = \iint_{D'} u \, du dv - \iint_{D'} (u^2 + v^2) \, du dv$$

根据对称性，奇函数 $u$ 在关于 $v$ 轴对称的单位圆盘 $D'$ 上的积分为 **0**。
对于第二项，使用极坐标 $u = r\cos\theta$, $v = r\sin\theta$：

$$- \iint_{D'} (u^2 + v^2) \, du dv = - \int_0^{2\pi} d\theta \int_0^1 r^2 \cdot r \, dr = -2\pi \cdot \left[ \frac{1}{4}r^4 \right]_0^1 = -\frac{\pi}{2}$$

**接着计算小圆盘 $D_1$ 上的积分：**
同样使用极坐标 $u = r\cos\theta$, $v = r\sin\theta$。区域 $D_1$ 的边界方程为 $r^2 = r\cos\theta$，即 $r = \cos\theta$。
积分的角度范围是 $-\frac{\pi}{2} \le \theta \le \frac{\pi}{2}$。

$$\begin{aligned}
\iint_{D_1} (u - u^2 - v^2) \, du dv &= \int_{-\pi/2}^{\pi/2} \int_0^{\cos\theta} (r\cos\theta - r^2) r \, dr d\theta \\
&= \int_{-\pi/2}^{\pi/2} \left[ \frac{1}{3}r^3\cos\theta - \frac{1}{4}r^4 \right]_0^{\cos\theta} d\theta \\
&= \int_{-\pi/2}^{\pi/2} \left( \frac{1}{3}\cos^4\theta - \frac{1}{4}\cos^4\theta \right) d\theta \\
&= \frac{1}{12} \int_{-\pi/2}^{\pi/2} \cos^4\theta \, d\theta
\end{aligned}$$

利用偶函数性质和 Wallis 公式（华里士公式）：

$$\int_{-\pi/2}^{\pi/2} \cos^4\theta \, d\theta = 2 \int_0^{\pi/2} \cos^4\theta \, d\theta = 2 \cdot \left( \frac{3 \cdot 1}{4 \cdot 2} \cdot \frac{\pi}{2} \right) = \frac{3\pi}{8}$$

代回原式得到：

$$\iint_{D_1} (u - u^2 - v^2) \, du dv = \frac{1}{12} \cdot \frac{3\pi}{8} = \frac{\pi}{32}$$

### 4. 得出最终结果

将上述两个积分的计算结果代入第 2 步化简的公式：

$$\begin{aligned}
I_2 &= 2 \iint_{D_1} (u - u^2 - v^2) \, du dv - \iint_{D'} (u - u^2 - v^2) \, du dv \\
&= 2 \left( \frac{\pi}{32} \right) - \left( -\frac{\pi}{2} \right) \\
&= \frac{\pi}{16} + \frac{\pi}{2} \\
&= \frac{9\pi}{16}
\end{aligned}$$

**最终答案：**

$$I_2 = \frac{9\pi}{16}$$