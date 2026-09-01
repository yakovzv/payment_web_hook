import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "supplier:application",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("SUPPLIER_PORT", "8002")),
        workers=1,
        lifespan="on",
    )