import os, sys

def main():
    if not os.path.exists(".env"):
        print("No .env found", file=sys.stderr)
        return
        
    out = []
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            if "=" in line:
                k, v = line.split("=", 1)
                # handle values with quotes already surrounding them
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                v = v.replace('"', '\\"')
                out.append(f'{k}: "{v}"')
                
    with open("env.yaml", "w") as f:
        f.write("\n".join(out))
        print("env.yaml generated successfully", file=sys.stderr)

if __name__ == "__main__":
    main()
