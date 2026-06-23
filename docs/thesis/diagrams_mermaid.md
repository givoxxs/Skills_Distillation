# Mermaid — Bốn biểu đồ kiến trúc pipeline tối ưu SKILL.md

---

## Hình 3.1 — Kiến trúc ba giai đoạn Teacher–Student–Judge

```mermaid
flowchart LR
    M0["📄 SKILL.md\n(Mₙ)"]
    RUB["📋 Rubric\n(cố định)"]
    STU["① Student\nGemma 4-26B\npar 5 TC"]
    JDG["② Judge\nHaiku 4.5\no = Σwᵢsᵢ → Sₙ"]
    TCH["③ Teacher\nHaiku 4.5\nViết lại SKILL.md"]
    G2{"CỔNG 2\nSₙ−Sₙ₋₁ < −0.10?"}
    G1{"CỔNG 1\nS_val ≥ S_base−0.10?"}
    G3{"CỔNG 3\nDừng?"}
    BEST["M_best\n(rollback)"]
    M1["📄 SKILL.md\n(Mₙ₊₁)"]
    DONE(["Kết thúc"])

    M0 --> STU
    RUB --> JDG
    STU -->|"outputs"| JDG
    JDG -->|"Sₙ + logs"| G2
    G2 -->|"Có — sụt điểm"| BEST
    G2 -->|"Không"| TCH
    TCH -->|"Mₙ₊₁ ứng viên"| G1
    G1 -->|"Chấp nhận"| M1
    G1 -->|"Hoàn tác"| M0
    M1 --> G3
    G3 -->|"Dừng"| DONE
    G3 -->|"Tiếp — vòng n+1"| M0

    style STU fill:#dbe4ff,stroke:#4a9eed
    style JDG fill:#e5dbff,stroke:#8b5cf6
    style TCH fill:#d3f9d8,stroke:#22c55e
    style M0  fill:#ffd8a8,stroke:#f59e0b
    style M1  fill:#ffd8a8,stroke:#f59e0b
    style RUB fill:#ffd8a8,stroke:#f59e0b
    style G2  fill:#ffc9c9,stroke:#ef4444
    style G1  fill:#ffc9c9,stroke:#ef4444
    style G3  fill:#fff3bf,stroke:#f59e0b
    style BEST fill:#ffe3e3,stroke:#ef4444
```

---

## Hình 3.2 — Biểu đồ tuần tự một vòng tối ưu

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant S as "Student<br/>(Gemma 4-26B)"
    participant J as "Judge<br/>(Haiku 4.5)"
    participant T as "Teacher<br/>(Haiku 4.5)"

    Note over O: Bắt đầu vòng n — nạp Mₙ

    loop Mỗi batch (batch_size = 5)
        par 5 TC đồng thời (concurrent_tcs = 5)
            O->>S: TC₁…TC₅ + SKILL.md (Mₙ)
        end
        S->>J: Outputs (docx / gif / văn bản)
        J-->>O: EvalResult · Sₙ
    end

    Note over O: Sₙ = avg(tất cả batch)

    alt CỔNG 2 — Sₙ − Sₙ₋₁ < −0.10
        O->>O: Rollback: SKILL.md = M_best · bỏ Teacher
    else Không sụt điểm
        O->>T: SKILL.md (Mₙ) + run_logs
        T-->>O: Mₙ₊₁ ứng viên

        alt CỔNG 1 — S_val ≥ S_base − 0.10 (3 TC rank 6–8)
            O->>O: Chấp nhận: SKILL.md = Mₙ₊₁
        else
            O->>O: Hoàn tác: SKILL.md = Mₙ
        end
        O->>O: Lưu snapshot SKILL_round_N.md
    end

    alt CỔNG 3 — Điều kiện dừng
        Note over O: ① Sₙ ≥ 0.70<br/>② |Sₙ−Sₙ₋₁| < 0.02 trong 3 vòng<br/>③ n = max_rounds
    else Chưa thỏa
        O->>O: Mₙ₊₁ → Mₙ mới · sang vòng n+1
    end
```

---

## Hình 3.3 — Biểu đồ tuần tự (chạy từng TC — tuần tự)

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant S as "Student<br/>(Gemma 4-26B)"
    participant J as "Judge<br/>(Haiku 4.5)"
    participant T as "Teacher<br/>(Haiku 4.5)"

    Note over O: Bắt đầu vòng n — nạp Mₙ

    loop Mỗi TC (TC₁ → TC₂ → … → TC_N  — tuần tự)
        O->>S: TCᵢ + SKILL.md (Mₙ)
        Note over S: Thực thi trong sandbox
        S->>J: output TCᵢ
        J-->>O: EvalResultᵢ (sᵢ)
    end

    Note over O: Sₙ = avg(s₁ … s_N)

    alt CỔNG 2 — Sₙ − Sₙ₋₁ < −0.10
        O->>O: Rollback: SKILL.md = M_best · bỏ Teacher
    else Không sụt điểm
        O->>T: SKILL.md (Mₙ) + run_logs
        T-->>O: Mₙ₊₁ ứng viên

        alt CỔNG 1 — S_val ≥ S_base − 0.10 (3 TC rank 6–8)
            O->>O: Chấp nhận: SKILL.md = Mₙ₊₁
        else
            O->>O: Hoàn tác: SKILL.md = Mₙ
        end
        O->>O: Lưu snapshot SKILL_round_N.md
    end

    alt CỔNG 3 — Điều kiện dừng
        Note over O: ① Sₙ ≥ 0.70<br/>② |Sₙ−Sₙ₋₁| < 0.02 trong 3 vòng<br/>③ n = max_rounds
    else Chưa thỏa
        O->>O: Mₙ₊₁ → Mₙ mới · sang vòng n+1
    end
```

---

## Hình 3.4 — Workflow tổng thể

```mermaid
flowchart TD
    A(["Bắt đầu"])
    A --> B["Nạp: SKILL.md (M₀) · test_cases.json · config.yaml"]
    B --> C["Sinh Rubric\n(một lần — cố định xuyên suốt)"]
    C --> D{"n ≤ max_rounds?"}
    D -->|"Không"| Z(["Kết thúc — xuất M_best + metrics"])

    D -->|"Có"| E["Student chạy N TC\n(Gemma 4-26B · sandbox · retry×3)"]
    E --> F["Judge chấm điểm\n(Haiku 4.5 · Rubric · ensemble)"]
    F --> G["Tổng hợp Sₙ = avg(tất cả TC)"]

    G --> H{"CỔNG 2\nSₙ − Sₙ₋₁ < −0.10?"}
    H -->|"Có — sụt điểm"| I["Rollback: SKILL.md = M_best"]
    I --> N

    H -->|"Không"| J["Teacher viết lại SKILL.md → Mₙ₊₁\n(Haiku 4.5 · run_logs thất bại)"]
    J --> K{"CỔNG 1\nS_val ≥ S_base − 0.10?\n(3 TC rank 6–8)"}
    K -->|"Chấp nhận"| L["SKILL.md = Mₙ₊₁"]
    K -->|"Hoàn tác"| M["SKILL.md = Mₙ (giữ nguyên)"]
    L --> N["Lưu snapshot · cập nhật M_best nếu Sₙ > S_best"]
    M --> N

    N --> O{"CỔNG 3\n① Sₙ ≥ 0.70\n② Hội tụ 3 vòng\n③ n = max_rounds"}
    O -->|"Dừng"| Z
    O -->|"Tiếp"| P["n = n + 1"]
    P --> D

    style A fill:#b2f2bb,stroke:#22c55e
    style Z fill:#b2f2bb,stroke:#22c55e
    style H fill:#ffc9c9,stroke:#ef4444
    style K fill:#ffc9c9,stroke:#ef4444
    style O fill:#fff3bf,stroke:#f59e0b
    style C fill:#ffd8a8,stroke:#f59e0b
```

---

## Hình 3.5 — Kiến trúc hệ thống (component view)

```mermaid
graph TB
    subgraph Input
        I1["SKILL.md (M₀)"]
        I2["test_cases.json"]
        I3["config.yaml · .env"]
    end

    subgraph Core["distillation_v2/"]
        ORCH["pipeline.py\nOrchestrator"]
        STU_S["stages/student.py"]
        JDG_S["stages/judge.py"]
        TCH_S["stages/teacher.py"]
        RUB_S["rubric.py"]
        ORCH --> STU_S
        ORCH --> JDG_S
        ORCH --> TCH_S
        ORCH --> RUB_S
    end

    subgraph Sandbox["skill_runner/ (subprocess)"]
        SB["Claude Code CLI\nworkspace riêng · retry×3"]
    end

    subgraph ExtAPI["External APIs"]
        OR["OpenRouter\nGemma 4-26B"]
        ANT["Anthropic API\nHaiku 4.5"]
    end

    subgraph Storage["Storage"]
        SK["skills/\nSKILL.md snapshots"]
        TC["test_cases/"]
        LOGS["run_logs/ · metrics.json"]
    end

    Input --> ORCH
    STU_S --> SB
    SB --> OR
    JDG_S --> ANT
    TCH_S --> ANT
    ORCH --> Storage

    style Core fill:#f0f4ff,stroke:#4a9eed
    style Sandbox fill:#e9ecef,stroke:#555
    style ExtAPI fill:#fff9db,stroke:#f59e0b
    style Storage fill:#f8f9fa,stroke:#aaa
```

---

*Tham số: τ₁ = τ₂ = 0.10 · stop\_threshold = 0.70 · converge\_delta = 0.02 · converge\_k = 3 · batch\_size = 5 · concurrent\_tcs = 5*
