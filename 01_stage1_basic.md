# 第一阶段：基础入门与“Hello World”

*类比 C 语言：了解编译器、变量定义、`main` 函数与 `printf`。*

---

## 1. 架构原理 (底层逻辑)

### 什么是 `nftables`？为什么要抛弃 `iptables`？

在 Linux 网络过滤的历史长河中，`iptables` 曾经是无可争议的统治者。但随着网络环境变得复杂，`iptables` 暴露出许多致命弱点：
- **性能瓶颈**：每次修改一条规则，哪怕只是加一个 IP，`iptables` 都要把整个规则集从内核拉到用户空间，修改后再整个塞回内核。规则数达到上万条时，重载几秒钟，这期间会导致网络停顿。
- **语法割裂**：IPv4 用 `iptables`，IPv6 用 `ip6tables`，ARP 分别用 `arptables` 和桥接 `ebtables`。管理起来像在使用四种不同的语言。

**`nftables` 的诞生就是为了解决这些问题：**
- **统一的框架**：一套命令（`nft`）通吃全栈（IPv4, IPv6, ARP, Bridge）。
- **极速的性能**：支持**增量更新**。修改一条规则，内核只更新那一条，毫秒级生效！
- **虚拟机架构**：`nftables` 在内核中实现了一个小型的虚拟机（如同 BPF），所有规则最终会被编译成虚拟机字节码执行，具有极高的灵活性。

### 核心基石：Linux 内核的 Netfilter 架构

无论是 `iptables` 还是 `nftables`，它们其实并不直接处理数据包，而是配置内核中一个叫做 **Netfilter** 的框架。

Netfilter 在内核网络协议栈的关键位置设置了 **5 个钩子（Hooks）**。你可以把这些钩子想象成大马路上的 5 个“收费站”或“检查站”。

> **Netfilter 的五大钩子（Hooks）：**
> 1. **PREROUTING:** 数据包刚刚进入网卡，还没进行路由选择（问路）前，先经过这里。
> 2. **INPUT:** 路由判断后，发现目的地址是本机，数据包进入本机应用之前，经过这里（保护本机）。
> 3. **FORWARD:** 路由判断后，发现目的地址不是本机，数据包只是路过并需要转发到另一张网卡，经过这里（路由器/网关行为）。
> 4. **OUTPUT:** 本机应用主动发出的包，在离开本机前往网卡之前，经过这里。
> 5. **POSTROUTING:** 数据包在即将离开网卡，进入物理网线之前，最后经过这里。

---

## 2. 核心三剑客 (基础数据类型)

学习 `nftables`，你只需要深刻理解三个概念。我们可以完全套用 C 语言的代码结构来理解：

### ① Table (表) —— 相当于 C 语言的 `namespace`（命名空间）

在 C 语言中，为了防止不同的模块函数名冲突，我们有命名空间。
在 `nftables` 中，**Table 就是隔离不同网络协议的命名空间。**

目前支持的协议族（Family）主要有：
- `ip`: IPv4 (默认)
- `ip6`: IPv6
- `inet`: 同时包含 IPv4 和 IPv6 （**最常用，强烈推荐**）
- `arp`: ARP 协议
- `bridge`: 桥接协议
- `netdev`: 硬件网卡级过滤，甚至比 PREROUTING 还早（用于防御 DDoS）。

> **语法：** `add table [family] [table_name]`

### ② Chain (链) —— 相当于 C 语言的 `函数 (Functions)`

有了命名空间，我们需要写函数。**Chain 就是挂载在 Netfilter 钩子上的函数。** 它是真正容纳执行逻辑（规则）的地方。

在 `nftables` 中，你创建的每一条链，都需要指定它挂载到哪个“检查站”（Hook）上。
当数据包路过那个“检查站”时，内核就会**调用**这个链（函数）。

> **语法：** `add chain [family] [table_name] [chain_name] { type filter hook input priority 0; policy accept; }`

### ③ Rule (规则) —— 相当于 C 语言的 `语句 (Statements)`

有了函数，我们在函数里面写具体的逻辑。**Rule 就是函数体内部的判断语句和执行动作。**

每一条 Rule 就像一条 `if (条件满足) { 执行动作 }` 语句。

> **语法：** `add rule [family] [table_name] [chain_name] [match_criteria] [action]`

---

## 3. Hello World (初试牛刀)

理论讲完，让我们用 `nftables` 写下我们的第一段“代码”。

### 零步：准备靶机环境 (Docker Lab)

为了不把自己的机器玩坏或断网，强烈建议使用 Docker 启动一个轻量级的 Alpine Linux 容器作为练习靶机：

```bash
# 在你的宿主机上，启动一个带特权模式的 Alpine 容器 (使用 tail -f /dev/null 保持后台存活)
docker run -itd --name nft-lab --privileged --network bridge alpine:latest tail -f /dev/null

# 进入容器内部终端
docker exec -it nft-lab /bin/sh

# 在容器内更新软件源并安装基础工具 (nftables, netcat-openbsd, iproute2)
apk update
apk add nftables netcat-openbsd iproute2
```

在接下来的所有实验中，你都在这个 `nft-lab` 容器内敲击 `nft` 配置或者开启 `nc` 监听，而在你的宿主机上进行发包测试。

---

**目标：** 写一个基础的包过滤防火墙，并编写我们的第一段逻辑：**拒绝所有外部对本机的 `ping`**。

### 第一步：清理现有环境

```bash
# 就像在写新代码前，清空旧的输出环境
sudo nft flush ruleset
```

### 第二步：编写 nftables 脚本文件

使用你最喜欢的文本编辑器，创建一个名为 `firewall_basic.nft` 的文件。

```nftables
#!/usr/sbin/nft -f

# 相当于 C 语言清空环境：清除系统中所有已存在的规则
flush ruleset

# ==========================================
# 1. 定义 Table（命名空间）
# 创建一个名为 "filter" 的 inet 表（兼顾 IPv4 和 IPv6）
# ==========================================
table inet filter {

    # ==========================================
    # 2. 定义 Chain（函数）
    # 创建一条名为 "input" 的链，专门处理发往本机的包
    # ==========================================
    chain input {
        # 函数签名：告诉内核这个函数挂哪里
        type filter hook input priority 0; policy accept;
        # 说明：
        # type filter  ->  用于数据包过滤
        # hook input   ->  挂载在 INPUT 这个检查站上
        # priority 0   ->  执行优先级，数字越小越先执行（通常填 0 即可）
        # policy accept->  默认策略：如果规则都没命中，默认放行包（为了防止自己被锁在门外，先设为 accept）

        # ==========================================
        # 3. 定义 Rule（具体的执行语句）
        # ==========================================

        # Hello World 实战：拒绝其他人 ping 我
        # 解释：如果协议是 icmp/icmpv6 (也就是 ping 用的协议)，且类型是 echo-request (要求响应)，则动作是 drop (直接把包丢弃，像丢进黑洞)。
        ip protocol icmp icmp type echo-request drop
        ip6 nexthdr icmpv6 icmpv6 type echo-request drop
        
        # 为了方便测试，下面这条规则可以暂时注释掉。
        # 当你确定不影响 SSH 后，可以放开。
        # tcp dport 22 accept
    }
}
```

### 第三步：运行脚本并测试

在将脚本应用之前，强烈建议先开**两个终端窗口**。如果你在远程服务器操作，一定要预留一条登录通道，以防把自己锁在外面（虽然上面的 `policy` 设为了 `accept`）。

运行你的脚本：
```bash
sudo nft -f firewall_basic.nft
```

查看内核当前的规则：
```bash
sudo nft list ruleset
```

### 测试你的 Hello World

现在，我们需要验证防火墙是否生效了！由于 Windows 和 Mac 系统上的 Docker 运行在虚拟机中，宿主机无法直接 ping 通容器的内网 IP（如 `172.17.x.x`）。为了最真实、准确地测试防火墙规则，我们**再启动一个客户端容器**来发起探测：

**1. 准备测试客户端：**
打开一个新的终端窗口：
```bash
# 启动一个临时的测试容器，连接到默认 bridge 网络
docker run -it --rm --network bridge alpine:latest /bin/sh

# 在测试容器内安装必需工具
apk add iputils netcat-openbsd
```

**2. 测试 Ping (预期被拦截)：**
在刚刚启动的**测试客户端容器**内部，尝试 Ping 被保护的靶机（`nft-lab`）：
```bash
# 获取 nft-lab 的 IP
# 可以在宿主机执行：docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' nft-lab
# 假设获取到的 IP 是 172.17.0.2

# 在测试客户端容器内尝试 Ping：
ping 172.17.0.2
```
你会发现：**请求超时！终端处于卡死（挂起）状态，因为你执行了 `drop`（把包丢进黑洞，没有任何回应）。**

**3. 测试其他端口用 `nc` (预期被放行)：**
因为我们在 `input` 链末尾设了 `policy accept`，所以没有被前面规则丢弃的流量应该都能进来。我们需要分别在**靶机**和**测试机**上操作。

**首先，在靶机 (`nft-lab`) 中开启监听（新开一个宿主机终端执行）：**
```bash
# 进入靶机并开启 8080 端口监听。这会占据当前终端，不要按 Ctrl+C 关闭它。
docker exec -it nft-lab nc -l -p 8080
```

**然后，回到之前那个测试客户端容器中用 `nc` 探测它：**
```bash
# 在测试客户端容器执行：
nc -vz 172.17.0.2 8080
```
你会看到立刻返回：`Connection to 172.17.0.2 8080 port [tcp/*] succeeded!`。同时靶机那边的监听终端会自动退出。

恭喜你！你已经通过实机验证，成功编写并运行了 `nftables` 版本的 "Hello World"。

---

> [!TIP]
> **思考：** `drop` 和 `reject` 有什么区别？
> - `drop`：直接丢弃，不给发送方任何回音。（仿佛发件人把信扔进了海里）对方只能一直干等到超时。**（推荐用于处理恶意流量，节省带宽）**
> - `reject`：拒绝，并礼貌地回复发送发：“我拒绝了你的请求（如：端口不可达）”。发送方的表现是立刻收到连接被拒绝的报错。**（推荐用于局域网内部友好的策略拦截）**
