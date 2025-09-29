import axios from 'axios';

// Log the environment variable to check its value
console.log("Backend URL:", process.env.REACT_APP_API_URL);

const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL
});

export default api;
