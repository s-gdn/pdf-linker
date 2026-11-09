"""Local data-only ONNX inference used by benchmarks and installed packs."""
from pathlib import Path
import json


class SemanticModel:
    def __init__(self, directory, spec=None):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np=np
        folder=Path(directory)
        self.spec=spec or json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        self.tokenizer=Tokenizer.from_file(str(folder/'tokenizer.json'))
        pad_id=self.tokenizer.token_to_id('[PAD]')
        pad='[PAD]'
        if pad_id is None:
            pad='<pad>';pad_id=self.tokenizer.token_to_id(pad)
        if pad_id is None:
            pad='<|endoftext|>';pad_id=self.tokenizer.token_to_id(pad)
        self.tokenizer.enable_padding(pad_id=pad_id or 0,pad_token=pad)
        self.tokenizer.enable_truncation(max_length=128)
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(folder/self.spec['weights']),options,providers=['CPUExecutionProvider'])
        self.cache={}

    def _run(self,texts):
        np=self.np
        encoded=self.tokenizer.encode_batch(texts)
        inputs={'input_ids':np.array([x.ids for x in encoded],dtype=np.int64),
                'attention_mask':np.array([x.attention_mask for x in encoded],dtype=np.int64),
                'token_type_ids':np.array([x.type_ids for x in encoded],dtype=np.int64)}
        length=inputs['input_ids'].shape[1]
        inputs['position_ids']=np.broadcast_to(np.arange(length,dtype=np.int64),inputs['input_ids'].shape)
        for item in self.session.get_inputs():
            if item.name.startswith('past_key_values.'):
                inputs[item.name]=np.zeros((len(texts),item.shape[1],0,item.shape[3]),dtype=np.float32)
        output_names=[o.name for o in self.session.get_outputs()]
        name='sentence_embedding' if self.spec.get('pooling')=='sentence' and 'sentence_embedding' in output_names else output_names[0]
        output=self.session.run([name],{i.name:inputs[i.name] for i in self.session.get_inputs()})[0]
        if self.spec.get('reranker'):
            return 1/(1+np.exp(-np.clip(output.reshape(-1),-50,50)))
        if output.ndim==3:
            pooling=self.spec.get('pooling','mean')
            if pooling=='cls':output=output[:,0]
            elif pooling=='last':
                positions=(inputs['attention_mask']*np.arange(1,length+1)).argmax(axis=1)
                output=output[np.arange(len(texts)),positions]
            else:
                mask=inputs['attention_mask'][...,None]
                output=(output*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1)
        return output/np.maximum(np.linalg.norm(output,axis=1,keepdims=True),1e-12)

    def encode(self,texts,*,query=False):
        prefix=self.spec.get('query_prefix',self.spec.get('prefix','')) if query else self.spec.get('document_prefix',self.spec.get('prefix',''))
        values=[prefix+text for text in texts]
        unseen=list(dict.fromkeys(t for t in values if t not in self.cache))
        for start in range(0,len(unseen),16):
            batch=unseen[start:start+16]
            self.cache.update(zip(batch,self._run(batch)))
        return self.np.array([self.cache[t] for t in values])

    def score(self,query,columns):
        if self.spec.get('reranker'):
            pairs=[(query,column) for column in columns]
            return self.np.concatenate([self._run(pairs[i:i+16]) for i in range(0,len(pairs),16)])
        return self.encode([query],query=True)[0]@self.encode(columns).T

    def prepare(self,queries,columns):
        if not self.spec.get('reranker'):
            self.encode(queries,query=True);self.encode(columns)
