# 第四阶段：状态机与内存管理 (进阶原理)

*类比 C 语言：状态机模式、指针与生命周期。*

---

在网络安全领域，防火墙分为两种：**无状态 (Stateless)** 和 **有状态 (Stateful)**。

回到第二阶段中我们留下的一个疑问：“如果没有 `ct state established,related accept` 这一条，你服务器主动去拉取外网的文件时，回来的包会被墙拦住”。为什么会这样？

因为在**无状态**防火墙（比如早期的路由器 ACL）眼里，它只认条件：
1. 你的请求包（源：本机，目的：百度，目的端口：443）出去时，匹配了 Output 链，放行。
2. 百度的响应包回来时（源：百度，目的：本机，随机高端口）。此时 Input 链检查条件，发现你只写了 “允许 80/443 和 SSH”，没有写允许百度的 IP 和随机端口。由于默认策略是 drop，响应包被无情丢弃。

难道每次你要访问一个新网站，都要去改一次防火墙规则吗？这显然不现实。

这就是**连接跟踪 (Connection Tracking, Conntrack)** 机制诞生的原因。

## 1. Conntrack (连接跟踪机制)

Netfilter 在内核里维护了一张巨大的内存表——**连接跟踪表**。当一个数据包经过防火墙时，Conntrack 模块会记录它的连接状态。

在 `nftables` 中，我们可以使用 `ct state` 来读取当前包在内核状态机中的状态值。4 种核心状态：

*   **`new`** (新建)：这是一个连接的第一个合法数据包（比如 TCP 的 SYN 包）。说明有人正在尝试跟你建立全新的连接。
*   **`established`** (已建立)：这个包属于一个双向都见过包的“熟人连接”。（比如 TCP 三次握手成功后的后续所有数据包）。
*   **`related`** (相关联的)：这个包不是已有连接的包，但它跟已有连接“有血缘关系”。最典型的例子是 FTP 数据端口协商，或者 ICMP 的报错信息（比如“端口不可达”是由之前某个 TCP/UDP 连接触发的）。
*   **`invalid`** (非法的)：内核认不出这是什么玩意儿。比如没经过握手直接发来的 RST 包，或者格式损坏的包。通常直接 `drop`。

### 为什么加上之后就行了？

当你在 Input 链的开头加上 `ct state established,related accept` 后：
1. 你主动访问百度。Output 出去的是 `new` 放行，内核 Conntrack 记下这条流。
2. 百度响应回来。内核一看，这个包属于你刚才发起的连接，于是打上 `established` 标签。
3. 包进入 Input 链，遇见第一条规则，匹配 `established`，直接放行！

**精妙之处**：你不需要在 Input 链里放开任何高危的随机端口，就能完美接收所有的合法回包。

---

## 2. 实用实战：安全的出站策略 (企业服务器标配)

在许多公司，服务器的安全要求是：**能且仅能主动访问外部，外部绝对不能主动连接进来（甚至连 SSH 都不能），除非走专门的堡垒机 VPN。**

这时候，防火墙的逻辑就非常简单且极其安全了。

文件：`corporate_server.nft`

```nftables
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # 【核心安全规则】
        # 只允许“已建立”或“相关”的连接进来。
        # 意味着：只有我主动找你的，你的回复才能进！你主动找我的 (new)，全被底下的 policy drop 拦在外面！
        ct state established,related accept
        ct state invalid drop

        # 允许本地回环
        iifname "lo" accept
        
        # 不要写任何其他的 accept！连 22 端口也不开，外部无法主动发起任何 new 的连接。
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        # 允许本机主动向外网发包。这些都是 new 状态，会被内核记录到状态机里。
        type filter hook output priority 0; policy accept;
    }
}
```

> [!TIP]
> **资源开销与抗攻击优化：**
> 状态机的代价是：每一条连接都会消耗内核内存。如果遇到 DDoS（比如 SYN Flood 攻击），短时间内产生海量的半连接态 `new` 会撑爆你的 Conntrack 表，导致新包无法进入。
> 高级应对方案是在 `nftables` 中关闭特定大流量端口的连接跟踪（使用 `notrack` 动作），退化为无状态防御。

### 验证状态机：坚不可摧的“单向”防火墙

**测试目标：** 测试客户端容器无法主动连接靶机，但靶机可以主动连接测试客户端容器并顺利收到回包。

**1. 验证外部无法主动进入：**
在靶机 `nft-lab` 内启动一个服务模拟（即使开了服务，外面也进不来）。新开一个终端执行：
```bash
docker exec -it nft-lab nc -l -p 8080
```
在**测试客户端容器**发起主动访问探测：
```bash
# 测试客户端容器执行
nc -vz 172.17.0.2 8080
# 预期结果：超时卡死！因为外面进来的第一个包属于 `new` 状态，未被 accept，最终掉入底层的 policy drop。
```

**2. 验证内部可以主动出去，且回包畅通无阻：**
在**测试客户端容器**（注意：这次是测试容器做服务端，假设它的 IP 是 `172.17.0.3`）开启监听，新开终端执行：
```bash
# 测试客户端终端执行
docker exec -it nft-client nc -l -p 9090
```
进入靶机 `nft-lab`，主动连接测试容器上面的 9090 端口：
```bash
# 靶机内执行
nc -vz 172.17.0.3 9090
# 预期结果：succeeded! 
```

**原理解释：**
- 靶机发出探测包（SYN），命中 `output` 链的 `policy accept` 放归，**同时状态机记录这个连接的状态**。
- 测试容器回复确认包（SYN+ACK）。包到达靶机的 `input` 链，命中第一条规则：`ct state established,related accept`！回包顺利放行。
- 这样，不需要开启任何高位端口，靶机就完成了网络通信。通过 `nc` 实测，状态机的生命周期展现得淋漓尽致。
