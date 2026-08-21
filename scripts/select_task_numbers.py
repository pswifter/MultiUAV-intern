import random


def main():
    numbers = random.sample(range(1, 21), 5)
    print("Selected task numbers:", " ".join(str(number) for number in numbers))


if __name__ == "__main__":
    main()
