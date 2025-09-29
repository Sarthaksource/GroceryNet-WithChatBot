import axios from 'axios';
const url = import.meta.env.REACT_APP_API_URL;

console.log(url)

const api = axios.create({
  // baseURL: "http://localhost:8000"
  baseURL: url
  // baseURL: "https://grocerynetwithchatbot.onrender.com"
});

export default api;
