<!-- graphify-review -->
## Graphify review: high risk

🔴 High risk (structural) · ✅ tests · ❌ reviewer

> **What changed.** total() now rounds its result. legacy\_tax() was deleted although checkout() still calls it.
>
> **Is it safe?** 🟠 Be careful. A removed helper is still referenced by checkout().

**Look at these first**

1. **legacy\_tax() removal** — checkout() still calls it `billing.py`

**Read the full review:** <https://reviews.example.test/pr-14/>

*Explanatory words are written by a model from the supplied evidence; they can be wrong and decide nothing.*
