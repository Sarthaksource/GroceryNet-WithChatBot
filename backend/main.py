from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import customer, order, product, bot  # Import the new bot router

app = FastAPI()

origins = ["https://grocerynet.netlify.app", "http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customer.router)
app.include_router(order.router)
app.include_router(product.router)
app.include_router(bot.router) 

@app.get("/")
def read_root():
    return {"message": "API and Webhook are running"}