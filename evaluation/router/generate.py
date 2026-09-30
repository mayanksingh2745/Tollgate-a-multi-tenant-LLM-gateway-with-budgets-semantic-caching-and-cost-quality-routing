"""Generate synthetic router benchmark dataset with diverse query distributions."""

import json
import random
from pathlib import Path
from typing import Any, Dict, List

DATASET_PATH = Path(__file__).parent / "datasets" / "router_benchmark.json"

# Simple queries where cheap models excel (cheap_sufficient = 1)
SIMPLE_TEMPLATES = [
    # Chit-chat & Greetings
    "Hello! How are you today?",
    "Hi there, good morning!",
    "Can you say hello in French, Spanish, and German?",
    "Thank you so much for your help!",
    "What is your name and what can you help me with?",
    "Tell me a short, clean joke about coffee.",
    "Give me an inspiring quote for Monday morning.",
    "Good evening! Hope you had a nice day.",
    # Definitions & Quick factual QA
    "What is the capital of France?",
    "Define the word 'serendipity'.",
    "How many days are in a leap year?",
    "Who painted the Mona Lisa?",
    "What is the boiling point of water in Celsius?",
    "What is the primary ingredient in guacamole?",
    "What is the largest ocean on Earth?",
    "Who wrote 'Romeo and Juliet'?",
    "What is photosynthesis in one sentence?",
    "What year did Apollo 11 land on the Moon?",
    "Name three primary colors.",
    "What is the currency of Japan?",
    "What does CPU stand for?",
    "How many continents are there?",
    "What is the chemical symbol for gold?",
    "What is the speed of light in vacuum?",
    "Name the planets in our solar system in order from the Sun.",
    # Simple summaries & Rewriting
    "Proofread this sentence: 'They went to there house yesterday.'",
    "Make this email polite: 'Send the report now.'",
    "Summarize this in one sentence: An apple is an edible fruit produced by an apple tree.",
    "Fix spelling: 'The restaraunt was beautifull.'",
    "Capitalize the following title: 'the great gatsby'",
    "Turn this into a bullet point: Today we discussed the budget, the timeline, and the hiring plan.",
    "Convert 68 Fahrenheit to Celsius.",
    "Suggest 3 baby names that start with the letter M.",
    "What is a synonym for 'happy'?",
    "Write a haiku about autumn leaves.",
    # Basic classification
    "Classify the sentiment: 'I absolutely love this new coffee machine!'",
    "Is 'apple' a fruit or a vegetable?",
    "Is 17 a prime number?",
    "Which is bigger: a kilowatt or a megawatt?",
    "Classify as fiction or non-fiction: 'A brief history of time'.",
]

# Complex queries requiring strong models (cheap_sufficient = 0)
COMPLEX_TEMPLATES = [
    # Math & Multi-step reasoning
    (
        "A train leaves Station A at 60 km/h. Two hours later, a second train leaves Station A "
        "traveling at 90 km/h on the same track. At what distance from Station A will the second train "
        "overtake the first? Solve step-by-step: 60 * (t + 2) = 90 * t.",
        "math_reasoning",
    ),
    (
        "Solve the differential equation dy/dx + 2y = e^(-x) with initial condition y(0) = 1. "
        "Show all integration factor steps: IF = exp(∫2 dx).",
        "math_calculus",
    ),
    (
        "A box contains 5 red balls, 4 green balls, and 3 blue balls. If you draw 3 balls without replacement, "
        "calculate the probability that exactly two balls have the same color. P(X=2) = ?",
        "math_probability",
    ),
    (
        "Prove that the square root of 2 is irrational using proof by contradiction. Assume √2 = p/q where gcd(p,q)=1.",
        "math_proof",
    ),
    (
        "Evaluate the limit as x approaches 0 of (sin(3x) - 3x) / x^3 using L'Hopital's Rule or Taylor series expansion.",
        "math_analysis",
    ),
    # SQL & Database queries
    (
        "Write a PostgreSQL query with CTEs to calculate 30-day rolling customer churn. "
        "SELECT customer_id, signup_date FROM subscriptions WHERE status = 'active' "
        "GROUP BY customer_id ORDER BY signup_date DESC;",
        "sql_query",
    ),
    (
        "Construct an optimized SQL query joining `orders`, `order_items`, and `products`. "
        "SELECT p.category, SUM(oi.quantity * oi.unit_price) AS total_revenue "
        "FROM orders o JOIN order_items oi ON o.id = oi.order_id "
        "JOIN products p ON oi.product_id = p.id "
        "WHERE o.status = 'completed' GROUP BY p.category HAVING SUM(oi.quantity * oi.unit_price) > 10000 "
        "ORDER BY total_revenue DESC;",
        "sql_query",
    ),
    (
        "Write an idempotent PostgreSQL migration to create an index concurrently on tenant_id and created_at. "
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tenant_created ON events(tenant_id, created_at);",
        "sql_migration",
    ),
    (
        "Explain the execution plan differences between Hash Join, Nested Loop, and Merge Join in PostgreSQL. "
        "Include indexing strategies for EXPLAIN ANALYZE SELECT * FROM users JOIN orders ON users.id = orders.user_id.",
        "sql_optimization",
    ),
    # Code generation & Refactoring
    (
        "Implement a thread-safe token bucket rate limiter in Python using asyncio and Redis. "
        "```python\nclass TokenBucketRateLimiter:\n    async def acquire(self, key: str, tokens: int) -> bool:\n        pass\n```",
        "code_generation",
    ),
    (
        "Refactor this recursive Fibonacci implementation to use matrix exponentiation for O(log n) time complexity. "
        "```python\ndef fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)\n```",
        "code_refactoring",
    ),
    (
        "Review this code for race conditions and memory leaks in C++ smart pointers: "
        "```cpp\nstd::shared_ptr<Node> a = std::make_shared<Node>();\nstd::shared_ptr<Node> b = std::make_shared<Node>();\na->next = b;\nb->prev = a;\n```",
        "code_review",
    ),
    (
        "Write a robust generic retry decorator in TypeScript that handles exponential backoff with jitter and abort signals. "
        "```typescript\nasync function retry<T>(fn: () => Promise<T>, options: RetryOptions): Promise<T>\n```",
        "code_generation",
    ),
    # JSON schema & Structured transformations
    (
        "Given the following nested JSON payload representing an e-commerce order: "
        '{"order_id": "123", "items": [{"id": "item1", "qty": 2, "price": 49.99}], "customer": {"id": "c1", "meta": {"loyalty_points": 340}}} '
        "Generate a strict JSON Schema Draft-07 that validates this structure and forbids extra properties.",
        "json_schema",
    ),
    (
        "Transform this JSON API response into OpenAPI 3.1.0 YAML schema with components and security schemes: "
        '{"status": "ok", "data": {"session_token": "xyz", "expires_at": 1700000000, "scopes": ["read", "write"]}}',
        "json_transformation",
    ),
    # System Architecture & Multi-turn long reasoning
    (
        "Design a distributed event-driven billing architecture capable of processing 100,000 transactions per second. "
        "Address idempotent consumer design, out-of-order event resolution, double-entry ledger invariant verification, "
        "and disaster recovery across two cloud regions.",
        "architecture_design",
    ),
    (
        "Analyze the security implications of utilizing JWTs vs opaque bearer tokens stored in Redis for distributed sessions. "
        "Compare revocation latency, replay attack mitigations, CSRF defenses, and cryptographic key rotation under CVE-2015-9235.",
        "security_analysis",
    ),
]


def generate_benchmark_dataset(num_samples: int = 300, seed: int = 42) -> List[Dict[str, Any]]:
    """Generate a balanced, deterministic dataset of chat completion requests."""
    random.seed(seed)
    dataset: List[Dict[str, Any]] = []

    # Target roughly 50% cheap sufficient, 50% strong required
    num_simple = num_samples // 2
    num_complex = num_samples - num_simple

    # 1. Simple samples
    for i in range(num_simple):
        prompt = SIMPLE_TEMPLATES[i % len(SIMPLE_TEMPLATES)]
        # Add slight variations to avoid duplicates
        if i >= len(SIMPLE_TEMPLATES):
            variations = [
                f"Please answer briefly: {prompt}",
                f"In 20 words or less: {prompt}",
                f"{prompt} Keep it simple.",
                f"Quick question: {prompt}",
            ]
            prompt = variations[(i // len(SIMPLE_TEMPLATES)) % len(variations)]

        messages = [{"role": "user", "content": prompt}]

        # Occasionally add a simple system prompt
        if random.random() < 0.3:
            messages.insert(
                0, {"role": "system", "content": "You are a concise, helpful assistant."}
            )

        dataset.append(
            {
                "id": f"benchmark_{len(dataset):04d}",
                "messages": messages,
                "cheap_sufficient": 1,
                "task_type": "simple_query",
                "quality_cheap": round(random.uniform(0.88, 0.99), 3),
                "quality_strong": round(random.uniform(0.92, 1.00), 3),
            }
        )

    # 2. Complex samples
    for i in range(num_complex):
        tmpl, task_type = COMPLEX_TEMPLATES[i % len(COMPLEX_TEMPLATES)]
        prompt = tmpl
        if i >= len(COMPLEX_TEMPLATES):
            var_prefix = [
                "Carefully analyze and provide an in-depth response: ",
                "Detail all edge cases and rigorous constraints: ",
                "Perform an exhaustive end-to-end breakdown: ",
                "Provide an expert-level technical solution: ",
            ]
            prompt = var_prefix[(i // len(COMPLEX_TEMPLATES)) % len(var_prefix)] + prompt

        messages = [{"role": "user", "content": prompt}]

        # Add realistic conversation depth for some complex items
        if random.random() < 0.4:
            messages = [
                {
                    "role": "system",
                    "content": "You are a principal engineer and domain specialist. Provide rigorous technical solutions.",
                },
                {
                    "role": "user",
                    "content": "We have an ongoing performance issue in our core transaction pipeline.",
                },
                {
                    "role": "assistant",
                    "content": "Please share the database schema, query patterns, and query execution plans so we can diagnose the bottleneck.",
                },
                {"role": "user", "content": prompt},
            ]

        dataset.append(
            {
                "id": f"benchmark_{len(dataset):04d}",
                "messages": messages,
                "cheap_sufficient": 0,
                "task_type": task_type,
                "quality_cheap": round(random.uniform(0.30, 0.65), 3),
                "quality_strong": round(random.uniform(0.85, 0.98), 3),
            }
        )

    # Shuffle deterministically
    random.shuffle(dataset)

    # Re-index ids
    for idx, item in enumerate(dataset):
        item["id"] = f"benchmark_{idx:04d}"

    return dataset


def save_benchmark_dataset(output_path: Path = DATASET_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset = generate_benchmark_dataset()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2)
    print(f"Generated {len(dataset)} benchmark samples -> {output_path}")


if __name__ == "__main__":
    save_benchmark_dataset()
