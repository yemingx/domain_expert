import { ConfigProvider, theme } from 'antd';
import Layout from './components/Layout';

function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      <Layout />
    </ConfigProvider>
  );
}

export default App;
