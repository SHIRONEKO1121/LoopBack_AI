from server import standardize_resolution

input_text = "Hi there! I am sorry to hear about your issue. I have gone ahead and reset your password. Please try logging in again at https://sso.acme.com. Let me know if it works!"
print(f"Original: {input_text}")
print("-" * 20)
standardized = standardize_resolution(input_text)
print(f"Standardized: {standardized}")
