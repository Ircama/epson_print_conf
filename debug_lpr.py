from pyprintlpr import LprClient
print("Class attributes:")
print(dir(LprClient))
with LprClient('127.0.0.1') as lpr:
    print("\nInstance attributes:")
    print(dir(lpr))
