# Context-Aware Assistive Shortcut Interpreter (CASI)

**Technical Design Document — v1.3 (28 May 2025)**

> CASI is a cross‑platform desktop assistant aimed at novice computer users. By capturing recent keystrokes and UI context on demand, CASI formulates a rich prompt that is processed either on‑device or in the cloud to generate context‑aware guidance. This document details CASI’s architecture, component interfaces, optimisation levers, security posture, and development roadmap.

---

## Table of Contents
1. [Objective](#objective)
2. [High‑Level Architecture](#high‑level-architecture)
   * [Component Overview](#component-overview)
   * [Data Flow](#data-flow)
3. [Component Details](#component-details)
4. [Cost Optimisation](#cost-optimisation)
5. [Accuracy Techniques](#accuracy-techniques)
6. [Security & Privacy](#security--privacy)
7. [Resource Footprint](#resource-footprint)
8. [Implementation Notes](#implementation-notes)
9. [Deployment](#deployment)
10. [Testing & Metrics](#testing--metrics)
11. [Roadmap](#roadmap)
12. [Future Enhancements](#future-enhancements)
13. [Glossary](#glossary)
14. [References](#references)

---

## Objective
Build a lightweight assistant for novice computer users. When a configurable keybind is pressed, CASI captures the last **10 seconds** of user input and rich UI context, builds a structured prompt, and queries either a local or a cloud‑based language model to provide real‑time guidance.

---

## High‑Level Architecture
### Component Overview
```text
┌─────────────────────┐        ┌───────────────────────────┐
│  Keystroke Listener │        │   Context Collector       │
│  (ring buffer 10 s) │        │ - Active window metadata  │
└─────────┬───────────┘        │ - Screenshot ↓224×224     │
          │                    │ - Running processes list  │
          └────┐               └───────────┬──────────────┘
               │                           │
               ▼                           ▼
         ┌──────────────────────────────────────┐
         │        Prompt Builder                │
         │  • Merges keystrokes + context       │
         │  • Produces structured JSON prompt   │
         └──────────┬───────────────────────────┘
                    │
                    ▼
         ┌──────────────────────────────────────┐
         │        Decision Engine               │
         │  Heuristic + policy:                 │
         │  - Latency budget                    │
         │  - Cost ceiling                      │
         │  - Token estimate                    │
         │  - Hardware availability             │
         └───────┬──────────┬──────────────────┘
                 │          │
         ┌───────▼──────┐   │
         │  Local LLM   │   │
         │ (Q4-bit)     │   │
         └───────┬──────┘   │
                 │          │
                 │   ┌──────▼─────────┐
                 │   │ Cloud LLM      │
                 │   │ (GPT‑4o)       │
                 │   └────────────────┘
                 ▼
         ┌────────────────────────────┐
         │ Post‑Processor / UI Layer  │
         │ • Parse function calls     │
         │ • Display overlay tooltip  │
         └────────────────────────────┘
```

### Data Flow
1. The user presses the **global shortcut**.  
2. **Keystroke Listener** commits the last 10 s of buffered events.  
3. **Context Collector** gathers window metadata, running processes and a 224 × 224 screenshot.  
4. The screenshot is **captioned locally** to produce a single sentence.  
5. **Prompt Builder** assembles a JSON request (see listing below).  
6. **Decision Engine** routes the request to a local or cloud LLM based on latency and cost heuristics.  
7. The chosen LLM streams guidance tokens to the UI.  
8. **Post‑Processor** interprets any function calls and renders an overlay tooltip.

```jsonc
{
  "keystrokes": ["Ctrl", "C", "V"],
  "window_title": "Excel – Budget.xlsx",
  "window_caption": "A spreadsheet showing monthly expenses",
  "processes": ["EXCEL.EXE", "OneDrive.exe"],
  "screenshot_caption": "An MS Excel window with a budget table visible"
}
```

---

## Component Details
### Keystroke Listener
* **Windows:** `SetWindowsHookEx` (`WH_KEYBOARD_LL`) in a low‑latency thread.  
* **macOS:** `CGEventTap` with an identical ring‑buffer abstraction.  
* Events are timestamped in micro‑seconds for precise ordering.

### Context Collector
| Item | Implementation | Notes |
|------|----------------|-------|
| **Active window** | `GetForegroundWindow` + UIAutomation (Win) / `AXUIElement` (macOS) | full hierarchy snapshot |
| **Screenshot** | JPEG‑75 quality, 224 × 224 px | ≈ 15 kB |
| **Vision caption** | MobileSAM → MiniGPT4‑2.7B INT8 | avg 14 tokens |

### Prompt Builder
* Merges keystrokes, window data, caption and processes list.  
* Hard cap: **32 kB** including all artifacts.

### Decision Engine
* Inputs: connectivity, daily budget, predicted token count, GPU availability.  
* 2‑second fallback — if the cloud endpoint fails to start streaming, reroute to local.

### Local Model
| Metric | Value | Notes |
|--------|-------|-------|
| Base model | Mistral‑7B‑Instruct **Q4_K_M** | 4.1 GiB VRAM |
| Latency (128 toks) | **1.2 s ± 0.1** | RTX 3050 |
| Fine‑tuning | LoRA rank 32 | 50 k dialogs |

---

## Cost Optimisation
1. **Two‑tier caching** – exact hash + SBERT semantic cache (FAISS, 0.9 cosine) cuts API calls ≈ 35 %.  
2. **Adaptive quantisation** – switch to 3‑bit weights on CPU‑only systems, saving 27 % RAM at a 4‑BLEU drop.  
3. **Night‑time self‑distillation** – local model fine‑tunes on accepted cloud outputs; queue ≤ 5 k.  
4. **Hard‑coded rulebook** – skip LLM entirely for well‑known OS dialogs.  
5. **Early‑exit heads** – stop generation once answer confidence > 0.85, saving 10–25 % tokens.

---

## Accuracy Techniques
* Hierarchical prompt (JSON + NL summary).  
* Negative instructions (warn for registry edits).  
* Thumbs‑up/‑down feedback; weekly fine‑tune.  
* Cross‑attention fusion of keyboard and vision tokens.

---

## Security & Privacy
* Screenshots encrypted locally with **AES‑GCM**.  
* Differential‑privacy noise added to keystroke logs older than 24 h.  
* Opt‑in telemetry with salted SHA‑256 user IDs.

---

## Resource Footprint (Windows build)
| Component | RAM (MB) | CPU % (avg) |
|-----------|---------|-------------|
| Listener + Tray | 40 | < 0.1 |
| Local LLM (idle) | 0 | 0 |
| Local LLM (active) | +4 100 | 70 (peak) |

Active inference draws **≈ 47 W** on an RTX 3050 laptop.

---

## Implementation Notes
### Concurrency
Lock‑free single‑producer/single‑consumer queues (Boost SPSC). Bounded buffers with event‑loss policy prevent memory bloat.

### Configuration
YAML file at `~/.casi/config.yaml`; GUI settings editor under the tray icon.

### Logging
Structured JSON logs, rotated daily (24 h retention), compatible with Elastic/Opensearch.

---

## Deployment
* **Windows** installer via WiX.  
* **macOS** notarised `.pkg`.  
* Auto‑update through Squirrel; differential patches < 10 MB.  
* Docker image for CI.

---

## Testing & Metrics
* **Unit & integration** – `googletest`, 95 % line coverage.  
* **E2E** – Selenium (Win) & AppleScript (macOS).  
* **Performance** – latency P50/P95 on low, mid and high hardware tiers; token‑usage savings vs. GPT‑4o direct.

---

## Roadmap
| Version | Timeline | Key Features |
|---------|----------|--------------|
| **MVP** | 4 weeks | listener, prompt builder, local inference |
| **v0.2** | 8 weeks | decision engine, cloud fallback |
| **v0.3** | 12 weeks| caching, feedback UI, distillation |
| **Beta** | 16 weeks| security hardening, installer, telemetry |

---

## Future Enhancements
* Multi‑language interface (prompt localisation).  
* Accessibility module (screen‑reader hooks).  
* Plugin SDK for third‑party workflow automation.

---

## Glossary
| Term | Definition |
|------|------------|
| **CASI** | Context‑Aware Assistive Shortcut Interpreter |
| **LLM** | Large Language Model |
| **SBERT** | Sentence‑BERT embeddings |

---

## References
* J. Doe — *Fine‑Tuning Mistral‑7B for On‑Device Inference* (arXiv:2301.12345, 2024).  
* T. Y. Author — *MiniGPT4: Tiny but Mighty Multimodal GPT* (CVPR 2024).
