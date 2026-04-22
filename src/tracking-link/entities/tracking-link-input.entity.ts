import { Column, Entity, PrimaryColumn } from 'typeorm';
import { SubscriberDto } from '../dto/subscriber.dto';

export type RiskLevel = 'no risk' | 'low' | 'high' | 'very high' | 'extreme';

@Entity('tracking_links_input')
export class TrackingLinkInput {
  @PrimaryColumn()
  id: string;

  @Column()
  trackingLinkId: string;

  @Column({ default: false })
  isProcessed: boolean;

  @Column({ type: 'jsonb' })
  subscribers: SubscriberDto[];
}
