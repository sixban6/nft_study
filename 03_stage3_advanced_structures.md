# 第三阶段：高级数据结构与优化 (性能飞跃)

*类比 C 语言：数组、哈希表、`switch-case` 语句。*

---

想象一下，你发现日志中每天有几百个恶意 IP 正在对你的服务器发起 SSH 爆破。你想把这些恶意 IP 全部封禁。

如果在老旧的 `iptables` 时代，你需要写出数百条这样的规则：
```bash
iptables -A INPUT -s 1.1.1.1 -j DROP
iptables -A INPUT -s 2.2.2.2 -j DROP
... (写 100 遍)
```
每收到一个新的数据包，内核就会把这 100 条规则从头到尾遍历比对一次。**时间复杂度是 O(N)**。随着黑客 IP 增多，你的服务器 CPU 开销也跟着猛涨。

针对这个问题，`nftables` 祭出了神器：高级数据结构。

## 1. Sets (集合：数组的超级进化)

`nftables` 原生支持集合（Sets）。你可以把成百上千个 IP、端口、甚至网段放到一个集合里面，用一行规则来搞定匹配。底层是用哈希表甚至更高级的树实现，这意味着无论集合里面有 10 个 IP 还是 10 万个 IP，查找匹配的**时间复杂度都是 O(1) 或者 O(logN)**！极大节省了 CPU 性能。

### ① 匿名集合 (Anonymous Sets)

在上一章我们其实已经用到了匿名集合。它的特点是没有名字，直接在大括号 `{ }` 中写明：

```nftables
# 匹配源 IP 在这几个当中的网络包
ip saddr { 1.1.1.1, 2.2.2.2, 8.8.8.8 } drop

# 匹配目标端口也是
tcp dport { 22, 80, 443, 8080 } accept
```

这种用法适用于**固定的、不需要怎么动态修改的数据**。如果每次想增删节点，都需要重写整个配置文件。

### ② 命名集合 (Named Sets)

这就是真正的神器了！我们可以在 Table 里提前定义好一个包含名字的盒子（集合），并且标明盒子里面存放的是什么“数据类型” （Type）。之后在过滤规则中引用这个盒子。

而且，这个集合能够在命令行时时**动态更新**，无需重启防火墙服务！

**实战用法展示：**

在脚本中定义：
```nftables
table inet filter {
    # 1. 定义一个名为 "blacklist" (黑名单) 的集合
    # 类型是 ipv4_addr (只能装 IPv4)，加上 flags interval 支持存放网段 (比如 /24)
    set blacklist {
        type ipv4_addr
        flags interval
        
        # 初始默认数据写在 elements 里面
        elements = { 
            1.1.1.1,
            2.2.2.0/24,   # 屏蔽整个网段
            100.100.100.100 
        }
    }

    chain input {
        type filter hook input priority 0; policy accept;
        
        # 2. 在规则中引用集合，使用 @ 符号
        # 逻辑：如果包的源地址在这个黑名单集合里，就直接滚。
        ip saddr @blacklist drop
    }
}
```

**动态运维命令：**
假设脚本起作用后，你巡检时又发现了一个恶意 IP `6.6.6.6`，你只需要在命令行直接增量插入：

```bash
# 即刻将其打入黑名单，不需要重载！
sudo nft add element inet filter blacklist { 6.6.6.6 }
```

这就是 C 语言指针和堆内存操作的魅力，地址绑定了一片内存，动态更新内存不会影响程序的其它逻辑！

---

## 2. Dictionaries & Vmaps (字典与决策图：超高性能的 Switch-case)

虽然集合把条件匹配优化到了 O(1)，但是“动作处理（Action）”呢？

假设一个包进来，如果是 22 端口我们要在日志记录并跳转到 SSH 处理逻辑；如果是 80 端口要跳转到 Web 逻辑。我们需要写多条带 `if-jump` 的语句，这种线性的层层判断依然不够优美且低效。

我们可以引入**Vmap（Verdict Maps，字典裁决映射图）**。
它就像 C 语言里的 `switch-case`，输入不同的键值（Key），输出并执行不同的执行动作（Verdict：放行/丢弃/跳转）。

### 什么是 Vmap？

它是一个键值对的集合。
- `Key`: 匹配的值（如端口 22）
- `Value`: 应当做的动作裁决（如 `jump chain_ssh` 或 `drop`）

### 实战：高性能路由分发与端口 Switch-case

让我们优化之前的 Web 服务器配置，利用 Vmap 根据不同的端口，分块跳转到对应的业务函数。

文件：`vmap_firewall.nft`

```nftables
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
    
    # --- 小函数 1：处理 SSH 的逻辑 ---
    chain handle_ssh {
        # 可以在这做限流、审计日志，这里直接放行
        accept
    }

    # --- 小函数 2：处理 Web 的逻辑 ---
    chain handle_web {
        accept
    }

    # --- 主函数入口 ---
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iifname "lo" accept

        # 【重点】定义一个 vmap 进行大分发
        # 语法：将目标端口的值 查找后面大括号里定义的映射关系
        # 如果端口是 22，则 vmap 返回：跳到 handle_ssh 这个链执行
        tcp dport vmap { 
            22 : jump handle_ssh, 
            80 : jump handle_web, 
            443: jump handle_web,
            23 : drop,   # 发现可疑 telnet，直接丢弃
            3306: drop   # 数据库不对公网开放
        }

        # 没有在上面 switch-case 中命中，或者虽然跳过去了但是没返回 accept 的包。
        # 会掉出上面的逻辑来到这里，然后触发 policy drop。
    }
}
```

**使用 Vmap 的极致好处：**
1. **代码结构巨清晰**：避免了面条代码（spaghetti code），真正实现了面向对象的模块化规则配置。
2. **性能巅峰**：Vmap 底层也是用哈希树或数组实现的。这意味着不管是几百个不同服务的端口，查找对应执行逻辑仅消耗 O(1) 的时间。

这就是 `nftables` 对 `iptables` 实现降维打击的秘诀：它让内核协议栈拥有了现代高级编程语言的执行效率！

### 验证 Vmap 字典分发机制

在 `nft-lab` 容器内部，准备测试环境：
```bash
# 分别模拟 SSH、Web 和一个被严打的 telnet 服务
nc -l -p 22 &
nc -l -p 80 &
nc -l -p 23 &
```

在**测试客户端容器**上进行实战探测：

**1. 测试合法的 SSH 和 Web 端口：**
```bash
# 在测试容器执行：
nc -vz 172.17.0.2 22
nc -vz 172.17.0.2 80
# 预期结果：succeeded! (命中了 22 和 80 的 vmap 规则，跳转后被 accept 放行)
```

**2. 测试明确被拦截的恶意服务 (23端口)：**
```bash
# 在测试容器执行：
nc -vz 172.17.0.2 23
# 预期结果：连接直接卡死超时 (命中了 23 的 vmap 规则，直接执行 drop)
```

这证明了无论是放飞还是拒绝，数据包到达 `tcp dport vmap` 这条语句时，就能通过 O(1) 的超高速字典查找瞬间决定去向。
