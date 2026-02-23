# 扩展阶段一：iproute2 核心原理 (Linux 路由基石)

*类比 C 语言：内存分页、静态指针与动态指针分发。*

当你掌握了 `nftables` 对数据包内容和修改的“生杀大权”后，你会发现还有一个决定数据包“生往何处”的关键大脑没有被触碰，那就是**路由表**。
过去我们习惯使用 `ifconfig`、`route` 甚至 `arp` 等零散的命令组合，这不仅功能孱弱而且缺乏统一框架。如今 Linux 真正唯一的网络管家叫做 `iproute2` 套件。

---

## 1. 告别 ifconfig 与 route (理解新架构)

为什么 `iproute2` 取代了老旧的 `net-tools`？
本质是因为 `iproute2` **直接使用底层且高效的 Netlink 套接字（Socket）与内核通信**，而旧的 `ifconfig` 依靠的则是陈旧的 ioctl 接口。同时，`iproute2` 提供了大一统的统一层级命令范式。

它的核心三要素如下：

1. **`ip link` (网卡硬件状态，类比：分配物理内存)**
   专门用于管理 OSI 第二层（数据链路层）的状态。你可以挂载网卡，更改 MAC 地址，建立虚拟网卡隧道。
   ```bash
   # 启用/禁用网卡
   ip link set eth0 up
   ip link set eth0 down
   ```

2. **`ip addr` (为变量赋 IP 地址，类比：变量赋值)**
   管理 OSI 第三层（网络层）的地址。在 Linux 中，一个网卡完全可以挂载无限多个 IP 地址。
   ```bash
   # 给 eth0 绑定一个新的 IP
   ip addr add 192.168.1.100/24 dev eth0
   # 查看地址
   ip addr show
   ```

3. **`ip route` (静态跳转指针，类比：无条件 Goto 语句)**
   这就是“发往何处”的绝对真理。所有的包，都会拿着目的 IP 地址，来路由表中做“最长前缀匹配”。
   ```bash
   # 查看当前的主路由表
   ip route show
   # 添加一条静态路由（访问 10.0.0.0/8 的流量，从 eth1 丢给网关 192.168.2.1）
   ip route add 10.0.0.0/8 via 192.168.2.1 dev eth1
   ```

---

## 2. 策略路由 Policy Routing (高级指针表)

传统的网络观念里，路由器只能有一个“默认网关”，路由完全是死板地“看目的地址下菜碟”。
**但在 Linux 高级路由中，这完全是个误区。Linux 其实有足足 255 张路由表（多级指针表）！** 

突破“单一默认网关”限制的黑魔法叫做**策略路由 (Policy Routing)**。
它的核心命令是 **`ip rule`**。它充当着**动态路由选择器（`switch-case`）**的角色。

### `ip rule` 的作用
`ip rule` 决定了：**当一个包产生时，我要去翻这 255 张路由表中的哪一张！**

比如：
- “如果是从上海电信接口（eth1）进来的包，去查第 100 号路由表”
- “如果是源 IP 是 192.168.1.50 发出的包，去查第 200 号路由表”

我们看一下内置的指针映射表：
```bash
$ ip rule show
0:      from all lookup local
32766:  from all lookup main
32767:  from all lookup default
```
这三条是系统自带的规则。数字是优先级（`priority`），越小越早执行。
所有的包都会匹配 `from all`，所以默认大家都在翻 `main`（主表，即平时 `ip route show` 看到的表）。

---

## 3. 路由实战：双线多拨与负载均衡

**背景描述：** 
假设你的服务器插了两根网线：
- `eth1`：电信宽带，IP为 10.1.1.2，网关 10.1.1.1
- `eth2`：联通宽带，IP为 10.2.2.2，网关 10.2.2.1

如果你只在主表里设置一条默认网关，另一条宽带就永远荒废了。如果外部电信用户访问你的联通 IP，回包会被迫从主路由的电信网关怼出去，这叫反规则（Asymmetric routing），大部分运营商防火墙会直接将其丢弃。

### 实战演练：源地址策略路由 (原路进原路出)

这是多线路由最经典的应用：“从哪张网卡进来的外网请求，回包也必须从哪张网卡回去”。

**步骤 1：创建两张自定义的私有路由表**
我们在 `/etc/iproute2/rt_tables` 中给这些数字起个优雅的名字：
```bash
echo "100 telecom" >> /etc/iproute2/rt_tables
echo "200 unicom" >> /etc/iproute2/rt_tables
```

**步骤 2：在私有表中填入专属网关 (指针定位)**
让 100 号（电信）表只走电信网关，200 号（联通）表只走联通网关。
```bash
# telecom 表：所有外网流量交给电信网关
ip route add default via 10.1.1.1 table telecom
# unicom 表：所有外网流量交给联通网关
ip route add default via 10.2.2.1 table unicom
```

**步骤 3：编写 ip rule (动态指针分发)**
我们设定规则：看数据包的自身源 IP。如果该包的源 IP 是电信分配给我们的 IP，就必须去翻那张写满了电信规则的 `telecom` 路由表！
```bash
ip rule add from 10.1.1.2 lookup telecom
ip rule add from 10.2.2.2 lookup unicom
```

**发生了什么？**
当联通客户端向服务器的 `eth2` (联通, 10.2.2.2) 发起请求时。服务器要回复包，这个回复包的**源 IP**必然是 10.2.2.2，**目的 IP** 是客户端。
当回复包要出站时，它来查路由。首先看 `ip rule`，优先级命中 `from 10.2.2.2`，于是它掉头去翻 `unicom` 表。
`unicom` 表里写了 `default via 10.2.2.1`。
完美！这个包毫无悬念地从联通线路（网关 10.2.2.1）飞出去了。

这就是 `iproute2` 真正的底层统治力。它与 `nftables` 的梦幻联动，更将开启一片翻云覆雨的新天地。接下来请看 **《扩展阶段二：nftables 与 iproute2 的梦幻联动》**。
