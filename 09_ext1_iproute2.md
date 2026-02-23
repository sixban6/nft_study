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

## 3. 路由实战：基于 Docker 的双线多拨场景 (可复现)

为了让你亲身体验 `iproute2` 的黑魔法，我们准备了一个极其逼真的 Docker 沙盒实验。

**实验拓扑：** 
- **isp_router (ISP 核心路由)**: 模拟具备严格反欺骗（rp_filter=1）的运营商节点。拥有三个接口：Telecom (`10.101.1.254`)、Unicom (`10.102.2.254`)、Internet (`10.100.64.254`)。
- **server (你的多线服务器)**: 插了两根网线，`eth0` (Telecom, `10.101.1.2`)，`eth1` (Unicom, `10.102.2.2`)。目前的默认网关只有 Telecom。
- **client (外网游荡的用户)**: 位于公网 (`10.100.64.2`)，想访问你的服务器。

### 步骤 0：启动实验环境
创建一个 `docker-compose.yml` 文件并启动：

```yaml
services:
  isp_router:
    image: alpine:latest
    container_name: isp_router
    cap_add: [NET_ADMIN]
    sysctls:
      - net.ipv4.ip_forward=1
      - net.ipv4.conf.all.rp_filter=1
      - net.ipv4.conf.default.rp_filter=1
    command: sh -c "apk add --no-cache iproute2 tcpdump && tail -f /dev/null"
    networks:
      telecom: { ipv4_address: 10.101.1.254 }
      unicom:  { ipv4_address: 10.102.2.254 }
      internet:{ ipv4_address: 10.100.64.254 }

  server:
    image: alpine:latest
    container_name: server
    cap_add: [NET_ADMIN]
    command: sh -c "apk add --no-cache iproute2 ping && ip route del default || true && ip route add default via 10.101.1.254 && tail -f /dev/null"
    networks:
      telecom: { ipv4_address: 10.101.1.2 }
      unicom:  { ipv4_address: 10.102.2.2 }
    depends_on: [isp_router]

  client:
    image: alpine:latest
    container_name: client
    cap_add: [NET_ADMIN]
    command: sh -c "apk add --no-cache iproute2 ping && ip route del default || true && ip route add default via 10.100.64.254 && tail -f /dev/null"
    networks:
      internet: { ipv4_address: 10.100.64.2 }
    depends_on: [isp_router]

networks:
  telecom:
    ipam: { config: [{ subnet: 10.101.1.0/24 }] }
  unicom:
    ipam: { config: [{ subnet: 10.102.2.0/24 }] }
  internet:
    ipam: { config: [{ subnet: 10.100.64.0/24 }] }
```
终端执行：`docker compose up -d`

---

### 第一幕：体验网络不通的绝望 (Asymmetric routing)

服务器 `server` 只有一条连向 Telecom 的默认网关。
如果外网 `client` 访问你的 Telecom IP：
```bash
docker exec client ping -c 1 10.101.1.2
# 结果：成功！包从电信口进，从电信口（默认网关）出。
```

但如果你访问它的 Unicom IP 呢？
```bash
docker exec client ping -c 1 10.102.2.2
# 结果：100% packet loss (超时)！
```
**原因分析：** 包从联通口（eth1）进来了。但是服务器想回包时，它只认识主路由表里的电信默认网关！于是包被强行塞进了电信接口发给 `isp_router`。`isp_router` 发现：怎么从电信口跑出来一个源 IP 是联通段的脏数据？直接作为欺骗攻击丢弃（`rp_filter` 机制）。

---

### 第二幕：iproute2 策略路由破局 (原路进原路出)

这是多线路由最经典的应用：“从哪张网卡进来的包，回包也必须从哪张网卡出去”。

**步骤 1：创建两张自定义的私有路由表**
我们在 `server` 容器里，给100号和200号表起个优雅的名字：
```bash
docker exec server sh -c "mkdir -p /etc/iproute2 && echo '100 telecom' >> /etc/iproute2/rt_tables && echo '200 unicom' >> /etc/iproute2/rt_tables"
```

**步骤 2：在私有表中填入专属网关 (指针定位)**
让 telecom 表只走电信网关，unicom 表只走联通网关。
```bash
docker exec server ip route add default via 10.101.1.254 table telecom
docker exec server ip route add default via 10.102.2.254 table unicom
```

**步骤 3：编写 ip rule (动态指针分发)**
我们设定规则：看数据包的自身源 IP。如果该包的源 IP 是电信分配给我们的 IP，就乖乖去翻那张写满了电信规则的 `telecom` 表！
```bash
docker exec server ip rule add from 10.101.1.2 lookup telecom
docker exec server ip rule add from 10.102.2.2 lookup unicom
```

### 见证奇迹的时刻

再次让外网客户端敲响那个原本打不通的联通 IP：
```bash
docker exec client ping -c 1 10.102.2.2
```
**结果：回显成功（TTL=63 time=0.0xx ms）！**

**发生了什么？**
当 `client` 请求服务器的未名口 (10.102.2.2) 时，服务器的回复包**源 IP**必然是 10.102.2.2。当回复包准备出站去查路由时，内核首先看到了 `ip rule` 拦截：
“优先级命中 `from 10.102.2.2`，掉头去翻 `unicom` 表！”
`unicom` 表里写了 `default via 10.102.2.254`。
完美！这个包毫无悬念地从联通线路原路返回了，避开了所有运营商的反欺骗检测。

这就是 `iproute2` 真正的底层统治力。它与 `nftables` 的梦幻联动，更将开启一片翻云覆雨的新天地。接下来请看 **《扩展阶段二：nftables 与 iproute2 的梦幻联动》**。
