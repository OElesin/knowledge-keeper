import axios from "axios";

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  headers: {
    "Content-Type": "application/json",
    "x-api-key": import.meta.env.VITE_API_KEY ?? "",
    "x-user-id": import.meta.env.VITE_USER_ID ?? "",
  },
});

export default apiClient;
