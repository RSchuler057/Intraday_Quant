def print_summary(name: str, summary: dict) -> None:
    print(f"\nStrategy: {name}")
    print("-" * 35)
    for key, value in summary.items():
        if isinstance(value, float):
            print(f"{key:<20}: {value:.4f}")
        else:
            print(f"{key:<20}: {value}")