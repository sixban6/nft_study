# 第二阶段：控制流与逻辑判断 (包过滤实战)

*类比 C 语言：`if-else` 条件判断、比较运算符、`return` 与 `break`。*

---

在第一阶段，我们了解了表、链、规则的基本骨架。现在我们要给“函数”里面填满具体的逻辑代码。在 `nftables` 中，所有的包过滤行为本质上就是对数据包的“头部信息”（IP头、TCP头等）进行一场巨大的 `if-else` 判断。

## 1. 匹配条件 (If 条件)

一条完整规则的格式是：`匹配条件 -> 动作`。可以有多个匹配条件，它们之间是逻辑与（**AND**）的关系。

### ① 网络层匹配 (基于 IP)

相当于判断 `if (packet.src_ip == "192.168.1.100")`

```nftables
# 匹配源 IP 地址 (saddr = source address)
ip saddr 192.168.1.100 drop

# 匹配目标 IP 网段 (daddr = destination address)
ip daddr 10.0.0.0/24 accept
```

### ② 传输层匹配 (基于协议与端口)

相当于判断 `if (packet.protocol == TCP && packet.dst_port == 22)`

```nftables
# 匹配单个端口 (tcp dport = TCP destination port)
tcp dport 22 accept
udp dport 53 accept

# 匹配多个端口段 (花括号在后续会详细讲，它是一个匿名集合)
tcp dport { 80, 443, 8080 } accept
tcp dport 1000-2000 drop
```

### ③ 接口匹配 (基于网卡)

相当于判断 `if (packet.interface == "eth0")`

```nftables
# 匹配入站网卡接口 (iifname = input interface name)
iifname "eth0" accept

# 匹配本地回环口 (非常重要，否则本地有些服务没法互相通信)
iifname "lo" accept
```

> [!WARNING]
> 大部分防火墙脚本的**第一条规则**，通常都是放行 `lo` (本地回环口 `127.0.0.1`) 流量。
> 语法表示：`iifname "lo" accept`。如果你忘了写，你的本地服务（比如 nginx 连本地 redis）可能会报错连不上。

---

## 2. 动作与控制流 (执行逻辑)

除了基础的 `accept`（放行）和 `drop/reject`（拒绝），我们还有控制程序流向的动作，类似于 C 的 `goto` 或函数调用。

### 基础动作：处理包的命运
- `accept`：立刻放行这个包。该包在这个钩子里**不再匹配此链下的其他规则**。（退出当前函数处理，并且包获准通过）
- `drop`：立刻丢弃，且不返回任何消息。
- `reject`：立刻拒绝，并回复一个 ICMP 错误消息。比如 `reject with tcp reset` 会立刻切断试图连接的扫描器。

### 进阶动作：控制流

当我们在一个 `input` 链（相当于 `main` 函数）中写了几千条规则时，代码会变得又长又难懂。在 C 语言中，我们会把代码**拆分成多个小函数**。在 `nftables` 中，我们可以创建**自定义链（Custom Chain）**。

- `jump [chain_name]`：跳转到目标自定义链去执行规则。如果目标链一直没有触发 accept/drop，执行完后会**弹回（return）**原先跳出的那条规则继续往下走。（这就完全是 C 语言的函数调用行为！）
- `goto [chain_name]`：跳转过去，**不回头了**。
- `return`：中止当前自定义链的执行，立刻返回上一级调用链。对于基础链（如 `input`, `forward`），返回就意味着采用这条链的 `policy` 默认动作。

---

## 3. 实用实战：打造基础 Web 服务器防火墙

我们将用所学的知识，编写一份用于真实生产环境 Web 服务器的基础防护脚本。

**业务需求：**
1. 默认策略是防御：任何人不准进（`policy drop`），只有明确允许的才能进。
2. 放行所有自己主动发出去请求的回包（重点：状态机，阶段四详解，这里先作为模板抄写）。
3. 放行本地 `lo` 回环接口。
4. 放行 SSH (端口 22) 以保证管理员登录，为了防止被扫描，限制只能从管理网段 `10.0.0.0/8` 访问。
5. 放行 HTTP (80) 和 HTTPS (443) 面向所有公网用户。
6. 放行 `ping`，方便网络测试诊断。

创建并编写文件 `web_server_fw.nft`：

```nftables
#!/usr/sbin/nft -f

# 清空旧规则
flush ruleset

table inet filter {
    # ---------------------------------------------
    # 主入口：Input 链
    # ---------------------------------------------
    chain input {
        # 挂载在 input 钩子上。
        # [!] 默认策略设为 drop (这是白名单模式，最安全的模式)
        type filter hook input priority 0; policy drop;

        # 1. 状态判断 (后续解释)：允许已建立的合法连接进来
        # 如果没有这一条，你服务器主动去拉取外网的文件时，回来的包会被墙拦住！
        ct state established,related accept
        # 防御机制：非法的状态包直接丢弃
        ct state invalid drop

        # 2. 允许本地回环口
        iifname "lo" accept

        # 3. 允许 ICMP (ping)
        ip protocol icmp accept
        ip6 nexthdr icmpv6 accept

        # ======== 业务规则区域 ========

        # 4. 允许 SSH 访问，只允许内网 10.0.0.0/8 网段
        ip saddr 10.0.0.0/8 tcp dport 22 accept

        # 5. 放行 Web 端口 (所有人都可以访问)
        # 看这里！我们将 80 和 443 放进一个花括号 {} 里，
        # 在内部会自动展开为匹配 80 或 443，比写两条规则更简洁性能更好！
        tcp dport { 80, 443 } accept
        
        # 其它没有被显式 accept 的流量，执行完这条链后，就会命中 policy drop 掉入黑洞。
    }

    # ---------------------------------------------
    # 转发与出站链 (本课暂不涉及，设为默认放行)
    # ---------------------------------------------
    chain forward {
        type filter hook forward priority 0; policy drop;
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}
```

> [!CAUTION]
> **危险操作警报：**
> 如果你的 SSH 不在 22 端口，或者你的管理机器 IP 不在 `10.0.0.0/8` 网段，贸然使用上面这个脚本，你的服务器将会把你 **立刻踢下线且再也连不上**，因为 `policy drop` 会拦截你。
>
> **解决思路：** 在测试防火墙时，先将 `policy drop` 改成 `policy accept`。把这句放在规则最后：`# 注意最后加上测试用的 reject，用来模拟 drop 但方便调试`
> 当确保不阻断自己连接之后，再把 default policy 收紧。

### 验证你的 Web 服务器防火墙

我们在 Docker 靶机中启动几个后台监听服务，这相当于我们跑起来了 Web 服务和 SSH 服务：
```bash
# 在 nft-lab 容器内执行：启动 80 和 22 端口，以及一个未授权的 8080 端口
nc -l -p 80 &
nc -l -p 22 &
nc -l -p 8080 &
```

回到之前准备好的**测试客户端容器**（即那个 `alpine` 容器），向靶机（假设 IP 为 `172.17.0.2`）发起测试：

**1. 测试放行的 Web 端口 (80)：**
```bash
# 在测试容器执行：
nc -vz 172.17.0.2 80
# 预期结果：succeeded! (规则：tcp dport { 80, 443 } accept)
```

**2. 测试限制源 IP 的 SSH 端口 (22)：**
```bash
# 在测试容器执行：
nc -vz 172.17.0.2 22
# 预期结果：超时卡死 (因为测试容器 IP 不在 10.0.0.0/8 网段，命中 policy drop)
```
*(注：如果你想让它通，可以把前面写脚本时的 `10.0.0.0/8` 临时改成测试容器的网段，比如 `172.17.0.0/16`)*

**3. 测试未放行的端口 (8080)：**
```bash
# 在测试容器执行：
nc -vz 172.17.0.2 8080
# 预期结果：超时卡死 (未被 accept，最终掉入 policy drop 的黑洞)
```

**4. 测试 Ping (ICMP)：**
```bash
ping -c 2 172.17.0.2
# 预期结果：正常收到回显 (规则：ip protocol icmp accept)
```

通过这套基于 `nc` 的实战，你可以真切体会到 `nftables` 对业务流量的精准拿捏。
