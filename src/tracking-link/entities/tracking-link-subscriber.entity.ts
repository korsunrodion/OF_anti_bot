import {
  Column,
  CreateDateColumn,
  Entity,
  PrimaryColumn,
  UpdateDateColumn,
} from 'typeorm';

export type RiskLevel = 'no risk' | 'low' | 'high' | 'very high' | 'extreme';

@Entity('tracking_links_subscriber')
export class TrackingLinkSubscriber {
  @PrimaryColumn()
  id: string;

  @Column()
  trackingLinkId: number;

  @Column()
  trackingLinkName: string;

  @Column()
  username: string;

  @Column()
  userId: number;

  @Column()
  subscriptionDate: string;

  @Column({ default: 0 })
  totalChargebacks: number;

  @Column({ default: 0 })
  totalSpent: number;

  @Column({ nullable: true })
  avatarUrl: string;

  @Column({ nullable: true })
  header: string;

  @Column({ nullable: true })
  isOnlineMatchesSubscription: boolean;

  @Column({ nullable: true })
  isReadingMessages: boolean;

  @Column({ nullable: true })
  riskLevel: RiskLevel;

  @Column({ default: false })
  isProcessed: boolean;

  @Column({ default: false })
  isInternalData: boolean;

  // Hides seeded rows from API responses; orthogonal to `isInternalData`,
  // which controls whether the Python predict job overwrites the label.
  @Column({ default: false })
  isInternalData2: boolean;

  @CreateDateColumn({ type: 'timestamptz' })
  createdAt: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  updatedAt: Date;
}
