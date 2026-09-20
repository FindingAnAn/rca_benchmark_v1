"""NumPy baselines: transparent statistics, ML, and actual deep neural training."""
import numpy as np
from .io import read_json, write_json


def sigmoid(x):
    return 1/(1+np.exp(-np.clip(x, -40, 40)))


class Baseline:
    def __init__(self, name, params, seed=42):
        if name not in ["stat_mad", "stat_ewma", "ml_logistic", "ml_pca", "dl_mlp", "dl_autoencoder"]:
            raise ValueError(f"Unknown algorithm {name}")
        self.name, self.params, self.seed = name, params, seed
        self.state = {}
        self.loss_history = []

    def fit(self, x, y, normal, feature_names):
        self.feature_names = list(feature_names)
        if not np.isfinite(x).all() or len(x) == 0:
            raise ValueError("Training matrix empty/nonfinite")
        if self.name.startswith("stat_"):
            return self
        unsup = self.name in ["ml_pca", "dl_autoencoder"]
        train = x[normal] if unsup else x
        if len(train) < 5:
            raise ValueError("Need at least five normal candidate observations")
        self.state["center"] = train.mean(axis=0)
        self.state["scale"] = np.maximum(train.std(axis=0), 0.1)
        z = self.transform(train)
        if self.name == "ml_pca":
            _, _, vt = np.linalg.svd(z, full_matrices=False)
            k = min(int(self.params["components"]), max(1, z.shape[1]-1), len(vt))
            self.state["basis"] = vt[:k]
            return self
        if not unsup and len(set(y.tolist())) < 2:
            raise ValueError("Supervised baseline needs both positive and negative labels")
        if self.name == "ml_logistic":
            hidden, output = [], 1
        elif self.name == "dl_mlp":
            hidden, output = self.params.get("hidden", [16, 8]), 1
        else:
            hidden, output = self.params.get("hidden", [16, 4, 16]), z.shape[1]
        if self.name.startswith("dl_") and len(hidden) < 2:
            raise ValueError("DL baseline requires at least two nonlinear hidden layers")
        rng = np.random.default_rng(self.seed)
        sizes = [z.shape[1], *hidden, output]
        weights = [rng.normal(0, np.sqrt(2/(a+b)), (a, b)) for a,b in zip(sizes, sizes[1:])]
        biases = [np.zeros(b) for b in sizes[1:]]
        moments = [(np.zeros_like(w), np.zeros_like(w), np.zeros_like(b), np.zeros_like(b))
                   for w,b in zip(weights,biases)]
        lr, l2 = self.params.get("lr", 0.01), self.params.get("l2", 0.001)
        targets = z if unsup else y.reshape(-1, 1)
        class_weights = np.ones((len(z), 1)) if unsup else np.where(targets==1,
                            len(y)/(2*max(1,sum(y))), len(y)/(2*max(1,len(y)-sum(y))))
        for epoch in range(1, self.params.get("epochs", 200)+1):
            activations = [z]
            for idx, (w,b) in enumerate(zip(weights,biases)):
                a = activations[-1]@w+b
                a = np.tanh(a) if idx < len(weights)-1 else (a if unsup else sigmoid(a))
                activations.append(a)
            prediction = activations[-1]
            if unsup:
                loss = np.mean((prediction-targets)**2)
                delta = 2*(prediction-targets)/prediction.size
            else:
                loss = -np.mean(class_weights*(targets*np.log(prediction+1e-12)+(1-targets)*np.log(1-prediction+1e-12)))
                delta = (prediction-targets)*class_weights/len(z)
            gradients = []
            for idx in range(len(weights)-1, -1, -1):
                gw = activations[idx].T@delta + l2*weights[idx]
                gb = delta.sum(axis=0)
                gradients.append((idx, gw, gb))
                if idx:
                    delta = (delta@weights[idx].T)*(1-activations[idx]**2)
            for idx, gw, gb in gradients:
                mw, vw, mb, vb = moments[idx]
                mw[:] = 0.9*mw+0.1*gw
                vw[:] = 0.999*vw+0.001*gw*gw
                mb[:] = 0.9*mb+0.1*gb
                vb[:] = 0.999*vb+0.001*gb*gb
                weights[idx] -= lr*(mw/(1-0.9**epoch))/(np.sqrt(vw/(1-0.999**epoch))+1e-8)
                biases[idx] -= lr*(mb/(1-0.9**epoch))/(np.sqrt(vb/(1-0.999**epoch))+1e-8)
            self.loss_history.append(float(loss))
        self.state.update(weights=weights, biases=biases)
        return self

    def transform(self, x):
        return np.clip((x-self.state["center"])/self.state["scale"], -20, 20)

    def score(self, x):
        if self.name.startswith("stat_"):
            def feature(name):
                return x[:, self.feature_names.index(name)] if name in self.feature_names else np.zeros(len(x))
            metric = "metric_max_abs_z" if self.name == "stat_mad" else "metric_ewma_z"
            return (feature(metric) + 2*feature("log_error_burst") + feature("log_error_rate") +
                    self.params.get("context_weight", 0)*(feature("recent_change") + feature("neighbor_evidence")))
        z = self.transform(x)
        if self.name == "ml_pca":
            b = self.state["basis"]
            return np.mean((z-z@b.T@b)**2, axis=1)
        a = z
        for idx, (w,b) in enumerate(zip(self.state["weights"],self.state["biases"])):
            a = a@w+b
            if idx < len(self.state["weights"])-1:
                a = np.tanh(a)
        return np.mean((z-a)**2, axis=1) if self.name == "dl_autoencoder" else sigmoid(a[:,0])

    def save(self, path):
        def serialize(v):
            return [a.tolist() for a in v] if isinstance(v,list) else v.tolist()
        write_json(path, dict(name=self.name, params=self.params, seed=self.seed,
                             feature_names=self.feature_names, loss_history=self.loss_history,
                             state={k:serialize(v) for k,v in self.state.items()}))

    @classmethod
    def load(cls, path):
        data = read_json(path)
        model = cls(data["name"], data["params"], data["seed"])
        model.feature_names = data["feature_names"]
        model.loss_history = data["loss_history"]
        model.state = {k:([np.array(a) for a in v] if k in ["weights","biases"] else np.array(v))
                       for k,v in data["state"].items()}
        return model
