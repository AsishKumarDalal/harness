Write a test file called `test_mathlib.py` for the `is_prime` function in
`mathlib.py`.

Use plain `assert` statements in a `main()` function guarded by
`if __name__ == "__main__":`, so the file can be run with
`python test_mathlib.py` (no pytest available).

Cover at least these cases: `is_prime(2)`, `is_prime(3)`, `is_prime(5)`,
`is_prime(7)`, `is_prime(11)` are True; `is_prime(0)`, `is_prime(1)`,
`is_prime(-3)`, `is_prime(4)`, `is_prime(9)`, `is_prime(25)` are False.
