import { useCallback, useEffect, useState } from "react";

export function useApi(loader, dependencies = [], options = {}) {
  const { immediate = true } = options;
  const [state, setState] = useState({ data: null, loading: immediate, error: null });

  const reload = useCallback(async () => {
    let active = true;
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const data = await loader();
      if (active) setState({ data, loading: false, error: null });
      return data;
    } catch (error) {
      if (active) setState({ data: null, loading: false, error });
      throw error;
    }
  }, dependencies);

  useEffect(() => {
    let active = true;
    if (!immediate) return () => { active = false; };
    setState((current) => ({ ...current, loading: true, error: null }));
    loader()
      .then((data) => { if (active) setState({ data, loading: false, error: null }); })
      .catch((error) => { if (active) setState({ data: null, loading: false, error }); });
    return () => { active = false; };
  }, dependencies);

  return { ...state, reload };
}
