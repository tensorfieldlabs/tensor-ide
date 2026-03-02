"""
primes.py - Utilities for prime number generation and checking.

Functions:
    is_prime(n)        -- Returns True if n is a prime number.
    first_n_primes(n)  -- Returns a list of the first n prime numbers.
"""

def is_prime(n):
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(n ** 0.5) + 1, 2):
        if n % i == 0:
            return False
    return True

def first_n_primes(n):
    primes = []
    candidate = 2
    while len(primes) < n:
        if is_prime(candidate):
            primes.append(candidate)
        candidate += 1
    return primes

if __name__ == "__main__":
    primes = first_n_primes(10)
    print("First 10 prime numbers:")
    print(primes)
