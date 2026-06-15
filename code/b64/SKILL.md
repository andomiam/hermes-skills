---
name: b64
description: "Custom base-64 encoder/decoder using alphabet 0-9A-Z_ a-z . (64 symbols). Encodes decimal integers to strings or decodes strings back. Master spec at /Knowledge/base64.md with implementations in Python, JS, C++, Rust, PHP, SQL."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [base64, encoding, custom-alphabet]
---

# Custom Base-64 Encoder/Decoder (b64_custom)

## Quick Reference

**Master spec:** `/home/master/Documents/Knowledge/base64.md` — full implementations in Python, JS, C++, Rust, PHP, SQL with TDD tests.

**Alphabet:** `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz.` (exactly 64 symbols)

## Function Signature
```
b64_custom(val, mode=0) → string/number
```

- **mode=0** (default): decimal integer → base-64 string
- **mode=1**: base-64 string → decimal integer
- Rejects negative numbers and invalid characters

## Python One-Liner Usage
```python
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz."

def b64_custom(val, mode=0):
    if mode == 0:
        n = int(val)
        res = []
        while n > 0 or len(res) == 0:
            res.append(ALPHABET[n % 64])
            n //= 64
        return ''.join(reversed(res))
    else:
        s = str(val).strip()
        res = 0
        for i, c in enumerate(reversed(s)):
            res += ALPHABET.index(c) * (64 ** i)
        return str(res)
```

## Examples
- `b64_custom(2025)` → `"7L"`
- `b64_custom("7L", 1)` → `"2025"`
- `b64_custom(0)` → `"0"` (zero boundary)
- `b64_custom(64)` → `"10"` (two-digit carry)

## Pitfalls
- **Zero handling**: mode=0 with input `0` returns `"0"`, not empty string. The loop condition `n > 0 or len(res) == 0` ensures this.
- **Arbitrary precision**: Python handles natively; JS needs BigInt; C++/Rust limited to u64/u128 unless using a big-int library.
- **Dot is value 63**: The `.` character represents the highest digit (index 63), not a separator or padding.
- **Periodic decimal expansion produces repeating tails**: When encoding rational numbers like 22/7, the result has a repeating tail pattern due to the periodic nature of the fraction's decimal expansion in base-64. This is expected — rational numbers with denominators that don't divide evenly into powers of 64 will always produce repeating sequences.
